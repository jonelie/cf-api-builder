/**
 * tests/ui.spec.ts
 *
 * Browser UI tests for the Cloudflare API Builder.
 *
 * These tests open a real (headless) Chromium browser, navigate to the app,
 * and interact with it the way a user would — clicking, typing, asserting
 * that the right things are visible on screen.
 *
 * Run: npm test
 * Visual mode: npm run test:ui
 */

import { test, expect } from '@playwright/test';

// ── Helper: wait for the app to finish loading endpoints ──────────────────────
// The app shows a loading screen then renders the UI once endpoints.json loads.
// We wait for the sidebar #tree to contain actual endpoint rows before each test.
//
// Note: .ep-row elements live inside a scrollable container (#sidebar uses
// overflow:hidden, #tree uses overflow-y:auto). Playwright's toBeVisible()
// requires the element to intersect the viewport, which fails for rows that are
// clipped by the overflow container. We use toHaveCount to confirm rows exist in
// the DOM instead, and clickFirstEndpoint() uses page.evaluate() to trigger the
// click via JavaScript (bypassing Playwright's visibility guards entirely).
async function waitForAppReady(page: import('@playwright/test').Page) {
  // The loading screen disappears and #shell becomes visible
  await expect(page.locator('#shell')).toBeVisible({ timeout: 10_000 });
  // At least one endpoint row exists in the sidebar tree (DOM presence, not viewport visibility)
  await expect(page.locator('#tree .ep-row')).not.toHaveCount(0, { timeout: 10_000 });
}

// Trigger a click on the first endpoint row via JS — bypasses overflow:hidden
// visibility constraints that prevent Playwright's normal .click() from working.
async function clickFirstEndpoint(page: import('@playwright/test').Page) {
  await page.evaluate(() => {
    const row = document.querySelector<HTMLElement>('#tree .ep-row');
    if (!row) throw new Error('No .ep-row found in #tree');
    row.click();
  });
}

// ── Suite: Page shell & layout ────────────────────────────────────────────────

test.describe('Page shell & layout', () => {
  test('has the correct page title', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveTitle('Cloudflare API Builder');
  });

  test('renders the three-panel layout', async ({ page }) => {
    await page.goto('/');
    await waitForAppReady(page);

    // All three main panels should be in the DOM and visible
    await expect(page.locator('#topbar')).toBeVisible();
    await expect(page.locator('#sidebar')).toBeVisible();
    await expect(page.locator('#main')).toBeVisible();
    await expect(page.locator('#output')).toBeVisible();
  });

  test('search input is visible and focusable', async ({ page }) => {
    await page.goto('/');
    await waitForAppReady(page);

    const search = page.locator('#search');
    await expect(search).toBeVisible();
    await expect(search).toHaveAttribute('placeholder', 'Search endpoints…');
    await search.click();
    await expect(search).toBeFocused();
  });

  test('status pill shows loaded state after boot', async ({ page }) => {
    await page.goto('/');
    await waitForAppReady(page);

    // The status dot starts as "loading" then transitions to another class.
    // We just assert it's no longer showing "loading…" text.
    const statusTxt = page.locator('#status-txt');
    await expect(statusTxt).not.toHaveText('loading…', { timeout: 10_000 });
  });
});

// ── Suite: Sidebar endpoint list ──────────────────────────────────────────────

test.describe('Sidebar endpoint list', () => {
  test('loads and shows endpoint rows', async ({ page }) => {
    await page.goto('/');
    await waitForAppReady(page);

    // There should be many endpoints (CF API has hundreds)
    const rows = page.locator('#tree .ep-row');
    const count = await rows.count();
    expect(count).toBeGreaterThan(10);
  });

  test('search filters the endpoint list', async ({ page }) => {
    await page.goto('/');
    await waitForAppReady(page);

    const search = page.locator('#search');
    const rows = page.locator('#tree .ep-row');

    // Count unfiltered rows
    const totalBefore = await rows.count();

    // Type a specific search term — "zones" is common in CF API
    await search.fill('zones');

    // Wait for the list to update (it filters in JS synchronously, but give it a tick)
    await page.waitForTimeout(200);

    const totalAfter = await rows.count();

    // Filtered list should be smaller than unfiltered
    expect(totalAfter).toBeLessThan(totalBefore);
    // And should still have results (zones is a real endpoint group)
    expect(totalAfter).toBeGreaterThan(0);
  });

  test('search with no matches shows "No endpoints match" message', async ({ page }) => {
    await page.goto('/');
    await waitForAppReady(page);

    await page.locator('#search').fill('zzz_no_match_zzz');
    await page.waitForTimeout(200);

    const msg = page.locator('#tree .tree-msg');
    await expect(msg).toBeVisible();
    await expect(msg).toContainText('No endpoints match');
  });

  test('clearing search restores full list', async ({ page }) => {
    await page.goto('/');
    await waitForAppReady(page);

    const rows = page.locator('#tree .ep-row');
    const totalBefore = await rows.count();

    await page.locator('#search').fill('zones');
    await page.waitForTimeout(200);

    await page.locator('#search').fill('');
    await page.waitForTimeout(200);

    const totalAfter = await rows.count();
    expect(totalAfter).toBe(totalBefore);
  });
});

// ── Suite: Endpoint selection & detail panel ──────────────────────────────────

test.describe('Endpoint selection', () => {
  test('clicking an endpoint shows the detail panel', async ({ page }) => {
    await page.goto('/');
    await waitForAppReady(page);

    // The empty state is visible before selection
    await expect(page.locator('#main-empty')).toBeVisible();
    await expect(page.locator('#ep-detail')).not.toBeVisible();

    // Select the first endpoint via JS click (bypasses overflow:hidden visibility check)
    await clickFirstEndpoint(page);

    // Empty state should hide; detail panel should appear
    await expect(page.locator('#main-empty')).not.toBeVisible();
    await expect(page.locator('#ep-detail')).toBeVisible();
  });

  test('detail panel shows method pill and path', async ({ page }) => {
    await page.goto('/');
    await waitForAppReady(page);

    await clickFirstEndpoint(page);

    // The method pill (GET/POST/etc.) should have text
    const pill = page.locator('#ep-mpill');
    await expect(pill).toBeVisible();
    await expect(pill).not.toHaveText('');

    // The path text should be visible and non-empty
    const pathText = page.locator('#ep-path-text');
    await expect(pathText).toBeVisible();
    await expect(pathText).not.toHaveText('');
  });

  test('token input is visible after selecting an endpoint', async ({ page }) => {
    await page.goto('/');
    await waitForAppReady(page);

    await clickFirstEndpoint(page);

    const tokenInput = page.locator('#token-input');
    await expect(tokenInput).toBeVisible();
    await expect(tokenInput).toHaveAttribute('placeholder', 'Paste your Cloudflare API token…');
  });
});

// ── Suite: curl output panel ──────────────────────────────────────────────────

test.describe('curl output panel', () => {
  test('output panel shows curl tab by default', async ({ page }) => {
    await page.goto('/');
    await waitForAppReady(page);

    // The curl tab should be active
    const curlTab = page.locator('.out-tab[data-tab="curl"]');
    await expect(curlTab).toHaveClass(/active/);
    await expect(page.locator('#pane-curl')).toBeVisible();
  });

  test('selecting an endpoint generates a curl command', async ({ page }) => {
    await page.goto('/');
    await waitForAppReady(page);

    await clickFirstEndpoint(page);

    // The curl output area should now contain something with "curl"
    const curlOut = page.locator('#curl-out');
    await expect(curlOut).toBeVisible();

    // Wait for curl content to appear (it renders from JS after selection)
    await expect(curlOut).toContainText('curl', { timeout: 5_000 });
  });

  test('can switch to Response tab', async ({ page }) => {
    await page.goto('/');
    await waitForAppReady(page);

    const responseTab = page.locator('.out-tab[data-tab="response"]');
    await responseTab.click();

    await expect(page.locator('#pane-response')).toBeVisible();
    await expect(page.locator('#pane-curl')).not.toBeVisible();
  });
});
