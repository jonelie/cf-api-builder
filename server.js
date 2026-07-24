/**
 * server.js
 * Cloudflare API Builder — Express backend
 *
 * Routes:
 *   GET  /                → public/index.html
 *   GET  /endpoints.json  → static build artifact (the endpoint index)
 *   ALL  /proxy/*         → proxies to https://api.cloudflare.com/client/v4/*
 *
 * The server only SERVES static files and proxies API calls. The endpoint index
 * (public/endpoints.json) is a build artifact produced by `npm run scrape`, so
 * the server boots instantly and never blocks on scraping. This also ports
 * cleanly to a Cloudflare Worker (static → Workers Assets; proxy → fetch handler;
 * endpoints.json → bundled import).
 */

import express from 'express';
import compression from 'compression';
import path from 'node:path';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT          = process.env.PORT || 3000;
const PUBLIC_DIR    = path.join(__dirname, 'public');
const ENDPOINTS_FILE = path.join(PUBLIC_DIR, 'endpoints.json');
const CF_API_BASE   = 'https://api.cloudflare.com/client/v4';

// Local dev runs same-origin (UI + proxy share the origin) so no CORS header is
// needed. For a future Worker/LAN deployment, set ALLOWED_ORIGIN to opt-in a
// specific origin. Avoid "*" — it lets any site the user is browsing drive
// their local proxy with a token they might have entered.
const ALLOWED_ORIGIN = process.env.ALLOWED_ORIGIN || null;

// Only these request headers are forwarded upstream (explicit allowlist).
const FORWARD_HEADERS = new Set(['authorization', 'content-type']);

// ── App ──────────────────────────────────────────────────────────────────────

const app = express();
app.disable('x-powered-by');
app.use(compression());                 // gzip responses (endpoints.json: 5.2MB → ~340KB)
app.use(express.json({ limit: '1mb' }));
app.use(express.static(PUBLIC_DIR, {
  maxAge: '1h',
  setHeaders(res, filePath) {
    if (filePath.includes(`${path.sep}fonts${path.sep}`)) {
      res.setHeader('Cache-Control', 'public, max-age=31536000, immutable');
    } else if (filePath.endsWith('.html') || filePath.endsWith('.json')) {
      // HTML and the endpoint index must revalidate so a re-scrape is picked up.
      res.setHeader('Cache-Control', 'no-cache');
    }
  },
}));

function applyCors(res) {
  if (ALLOWED_ORIGIN) res.setHeader('Access-Control-Allow-Origin', ALLOWED_ORIGIN);
}

// ── Proxy ──────────────────────────────────────────────────────────────────────

app.all('/proxy/*path', async (req, res) => {
  const rawPath = req.params.path;
  const normalizedPath = (Array.isArray(rawPath) ? rawPath : [rawPath])
    .filter(Boolean)
    .join('/');
  const proxyPath = '/' + normalizedPath;
  const qs = Object.keys(req.query).length
    ? '?' + new URLSearchParams(req.query).toString()
    : '';
  const upstreamUrl = `${CF_API_BASE}${proxyPath}${qs}`;

  const forwardHeaders = { host: 'api.cloudflare.com' };
  for (const [k, v] of Object.entries(req.headers)) {
    if (FORWARD_HEADERS.has(k.toLowerCase())) forwardHeaders[k] = v;
  }

  try {
    const hasBody = !['GET', 'HEAD'].includes(req.method.toUpperCase());
    const upstream = await fetch(upstreamUrl, {
      method: req.method,
      headers: forwardHeaders,
      body: hasBody ? JSON.stringify(req.body) : undefined,
      signal: AbortSignal.timeout(30_000),
    });

    res.status(upstream.status);
    for (const [k, v] of upstream.headers.entries()) {
      if (k === 'set-cookie' || k === 'transfer-encoding' || k === 'content-encoding') continue;
      res.setHeader(k, v);
    }
    applyCors(res);
    res.end(Buffer.from(await upstream.arrayBuffer()));
  } catch (err) {
    console.error('[proxy]', err.message);
    res.status(502).json({ error: 'Bad gateway', detail: err.message });
  }
});

app.options('/proxy/*path', (req, res) => {
  applyCors(res);
  if (ALLOWED_ORIGIN) {
    res.setHeader('Access-Control-Allow-Methods', 'GET,POST,PUT,PATCH,DELETE,HEAD,OPTIONS');
    res.setHeader('Access-Control-Allow-Headers', 'Content-Type,Authorization');
  }
  res.sendStatus(204);
});

// ── Start ─────────────────────────────────────────────────────────────────────

app.listen(PORT, () => {
  console.log(`\n  Cloudflare API Builder`);
  console.log(`  ─────────────────────────────`);
  console.log(`  http://localhost:${PORT}\n`);
  if (!existsSync(ENDPOINTS_FILE)) {
    console.log('  ⚠  public/endpoints.json not found.');
    console.log('     Run "npm run scrape" to generate the endpoint index.\n');
  }
});
