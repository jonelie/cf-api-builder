# Cloudflare API Builder - Session Notes

## Goal
Build a reliable API Builder that helps users generate correct Cloudflare API calls (curl + request body) when docs are hard to interpret, especially for nested object/array payloads.

## What We Accomplished

### 1) Nested schema support (major)
- Reworked scraper output to preserve nested request schema instead of flattening fields.
- `scraper.py` now parses docs structure recursively (`stldocs-expander`, nested children).
- Output now includes recursive `properties` for objects and `items` for arrays.
- Added merge handling for variants/entries/items so union-heavy endpoints are usable.

### 2) UI now consumes real nested schemas
- Removed one-off fixture approach.
- `public/index.html` now uses endpoint schema data directly for body rendering.
- Nested form rendering works across endpoints, including arrays-of-objects.
- Curl builder now constructs nested JSON payloads correctly from field input.

### 3) Token input UX fixed
- Token field supports typing and paste reliably.
- Added explicit `Paste` button and `Hide/Show` toggle.
- Improved token state syncing on input/change/paste.

### 4) Proxy route issue fixed (`7000 No route for that URI`)
- Root cause: wildcard path handling under Express 5.
- Patched `server.js` to normalize wildcard route segments safely before proxying.
- Verified with Playwright regression test that request path substitution/proxying works.

### 5) Automated regression added
- Added UI regression test:
  - `tests/regression-send.spec.ts`
- Test validates:
  - `zone_id` substitution is applied (no `%7Bzone_id%7D`)
  - Send Request response does not contain `No route for that URI`.

### 6) Pushed to GitHub
- Repo: `https://github.com/jonelie/cf-api-builder` (public, `main` branch).
- Verified no secrets/credentials before pushing (token is user-entered
  client-side only, never hardcoded; test fixtures use obviously-fake
  tokens/IDs like `fake_token_abc123`).
- `.gitignore` excludes `node_modules/`, `test-results/`, `playwright-report/`,
  `__pycache__/`, `.env`; `public/endpoints.json` + manifest are intentionally
  committed so the app works on a fresh clone without re-scraping.

### 7) Cloudflare Worker deployment option added
- `src/worker.js` — reimplements just the `/proxy/*` handler using standard
  Fetch API (`fetch`, `Headers`, `AbortSignal.timeout`); streams
  `request.body` straight through instead of buffering/re-serializing JSON
  like `server.js` does.
- `wrangler.jsonc` — static assets served from `public/` automatically via
  Workers Static Assets (zero code needed for that part); `main` points at
  `src/worker.js` for the proxy route only.
- **Important gotcha resolved:** initially pinned a newer `wrangler`
  devDependency (4.114.0) to fix `npm audit` vulnerabilities in local-dev
  tooling (esbuild/miniflare/sharp/undici/ws) — but that requires Node 22,
  and the machine's global `wrangler` (4.83.0, Homebrew) + default Node (20)
  didn't match. This caused two real errors:
  - `wrangler dev` (global binary) failed on `compatibility_date` too recent
    for that binary's supported range.
  - `npm run dev:worker` (local binary) failed requiring Node 22.
  - **Resolution:** reverted to the simplest working setup — no pinned
    `wrangler` devDependency (uses whatever `wrangler` is globally installed),
    `compatibility_date` set to `"2026-04-22"` (the exact max date the
    installed global `wrangler` 4.83.0 supports), no `.nvmrc`/Node 22
    requirement. Traded away the audit fix (those vulns are in local-only
    dev tooling, not the deployed Worker runtime) in favor of "just works."
  - Also hit a stale `.wrangler/state` SQLite schema conflict (leftover from
    testing the newer wrangler version) — fixed by deleting `.wrangler/`
    (safe, gitignored, local-only cache).
- `server.js` (Express) is completely untouched and still the default way to
  run the app (`npm start`); the Worker version is additive, not a
  replacement. No live `wrangler deploy` has been run yet — only verified
  locally with `wrangler dev`.

## Key Files Changed
- `scraper.py`
- `public/index.html`
- `server.js`
- `requirements.txt` (BeautifulSoup dependency)
- `tests/regression-send.spec.ts`
- `src/worker.js`, `wrangler.jsonc` (new — Worker deployment option)
- `package.json` (added `dev:worker`/`deploy` scripts)
- Generated artifacts:
  - `public/endpoints.json`
  - `public/endpoints-manifest.json`

## Current Status
- Builder is functioning with real nested schema rendering.
- Token entry and paste work.
- Proxy path bug is fixed in code and covered by regression test.
- Project is in a much better state and testable.
- Pushed to GitHub (`jonelie/cf-api-builder`), verified secret-free.
- Cloudflare Worker deployment option exists and is verified working locally
  via `wrangler dev` (static assets + `/proxy/*` both confirmed) — not yet
  deployed live.

## Pending / Next Steps

### Product / UX
- Add "Simple mode" for large GET endpoints (show common query params first, advanced collapsed).
- Improve handling/display for object-style query params (`name`, `content`, `comment`) so they are less intimidating.

### Data / Parser quality
- Add scraper invariants to detect accidental wrapper layers or malformed nesting early.
- Add quick schema sanity checks for top critical endpoints after each scrape.

### Testing
- Expand Playwright coverage:
  - DNS settings nested body happy-path
  - DNS record create with nested `settings`
  - rulesets array item add/remove and payload build
- Keep regression for proxy route and path substitution.

### Ops / reliability
- Always restart server after backend changes before manual testing.
- Keep using `CI=1 npx playwright test ...` for fresh-server validation.

## Future Plan
- Worker deployment option is done (see above) but not promoted to the
  primary way of running this app — `server.js`/`npm start` remains the
  default. Live `wrangler deploy` to a real Cloudflare account has NOT been
  run yet; only `wrangler dev` (local) has been verified.
- If/when Jon wants a live deployment: confirm target Cloudflare account,
  then `npm run deploy`.

## Resume Checklist for Next Session
1. `npm start` (Express) — verify app loads and token input works.
2. Run regression:
   - `CI=1 npx playwright test tests/regression-send.spec.ts`
3. Optional — verify the Worker path still works:
   - `npm run dev:worker` (uses global `wrangler`; no Node/version manager
     setup needed)
   - Check `GET /` and `GET /proxy/zones` respond correctly on
     `http://localhost:8787`
4. Choose next priority:
   - GET simple-mode UX
   - scraper invariants
   - broader Playwright suite
   - live Worker deployment (only when explicitly requested — confirm
     target Cloudflare account first)
