/**
 * src/worker.js
 * Cloudflare API Builder — Worker proxy handler
 *
 * Static assets (public/index.html, public/endpoints.json, fonts) are served
 * automatically by Workers Static Assets before this fetch handler ever runs —
 * see the "assets" block in wrangler.jsonc. This file only handles the one
 * dynamic route: proxying requests to the real Cloudflare API so the browser
 * doesn't need to deal with CORS, and so the user's token never leaves the
 * request that they explicitly send.
 *
 * Routes:
 *   ALL  /proxy/*  → proxies to https://api.cloudflare.com/client/v4/*
 *   *              → 404 (never reached for anything under public/, since
 *                    Workers Assets intercepts those requests first)
 */

const CF_API_BASE = 'https://api.cloudflare.com/client/v4';

// Only these request headers are forwarded upstream (explicit allowlist),
// mirroring server.js's behavior.
const FORWARD_HEADERS = new Set(['authorization', 'content-type']);

export default {
  async fetch(request) {
    const url = new URL(request.url);

    if (!url.pathname.startsWith('/proxy/')) {
      return new Response('Not found', { status: 404 });
    }

    if (request.method === 'OPTIONS') {
      // Same-origin local/dev usage doesn't need CORS headers here; kept as a
      // simple 204 so preflight requests don't fail if they ever occur.
      return new Response(null, { status: 204 });
    }

    const proxyPath = url.pathname.slice('/proxy'.length) || '/';
    const upstreamUrl = `${CF_API_BASE}${proxyPath}${url.search}`;

    const forwardHeaders = new Headers({ host: 'api.cloudflare.com' });
    for (const [key, value] of request.headers) {
      if (FORWARD_HEADERS.has(key.toLowerCase())) forwardHeaders.set(key, value);
    }

    const hasBody = !['GET', 'HEAD'].includes(request.method.toUpperCase());

    try {
      const upstream = await fetch(upstreamUrl, {
        method: request.method,
        headers: forwardHeaders,
        // Stream the body straight through instead of buffering/re-serializing
        // it (the Express version parses JSON then re-stringifies — the
        // Workers runtime lets us just pass the ReadableStream along).
        body: hasBody ? request.body : undefined,
        signal: AbortSignal.timeout(30_000),
      });

      const respHeaders = new Headers();
      for (const [key, value] of upstream.headers) {
        if (key === 'set-cookie' || key === 'transfer-encoding' || key === 'content-encoding') continue;
        respHeaders.set(key, value);
      }

      return new Response(upstream.body, { status: upstream.status, headers: respHeaders });
    } catch (err) {
      return new Response(JSON.stringify({ error: 'Bad gateway', detail: err.message }), {
        status: 502,
        headers: { 'content-type': 'application/json' },
      });
    }
  },
};
