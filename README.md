# Cloudflare API Builder

Interactive local tool for exploring Cloudflare API endpoints, filling request parameters, generating curl commands, and sending requests through a local proxy.

## Quick Start
- Install dependencies: `npm install`
- Generate endpoint data: `npm run scrape`
- Start app: `npm start`
- Open: `http://localhost:3000`

## Session Handoff Notes
- For latest progress, goals, and pending work, see:
  - `SESSION_NOTES.md`

## Testing
- Run all Playwright tests: `npm test`
- Run focused regression: `CI=1 npx playwright test tests/regression-send.spec.ts`

## Cloudflare Worker (alternative deployment)
The app also runs as a Cloudflare Worker — `public/` is served via Workers
Static Assets, and `src/worker.js` reimplements just the `/proxy/*` handler.
`server.js` (Express) is unaffected and still works the same way.

- Uses whichever `wrangler` CLI you have installed globally (no project-local
  version pinned) — install with `npm install -g wrangler` if you don't have it.
- Local dev: `npm run dev:worker` (starts `wrangler dev` on `http://localhost:8787`)
- Deploy: `npm run deploy` (not yet run against a live account — verify with
  `wrangler dev` first)

## Future Plan
- Worker deployment is available (see above) but not yet promoted to the
  primary way of running this app; `server.js` remains the default (`npm start`).
