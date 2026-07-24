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

## Future Plan
- We plan to migrate this app to a Cloudflare Worker when explicitly requested.
# cf-api-builder
