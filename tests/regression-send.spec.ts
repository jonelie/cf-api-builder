import { test, expect } from '@playwright/test';

async function waitForAppReady(page: import('@playwright/test').Page) {
  await expect(page.locator('#shell')).toBeVisible({ timeout: 10_000 });
  await expect(page.locator('#tree .ep-row')).not.toHaveCount(0, { timeout: 10_000 });
}

test('sending DNS list request does not use placeholder route', async ({ page }) => {
  await page.goto('/');
  await waitForAppReady(page);

  await page.locator('#search').fill('List DNS Records');
  await page.waitForTimeout(250);

  // Click first matched row via JS to avoid overflow visibility constraints.
  await page.evaluate(() => {
    const row = document.querySelector<HTMLElement>('#tree .ep-row');
    if (!row) throw new Error('No endpoint rows found after search');
    row.click();
  });

  const zoneId = '719c5874c752fc34d614ea14cd91629c';
  await page.locator('[data-key="path_zone_id"]').fill(zoneId);
  await page.locator('#token-input').fill('invalid-token-for-regression-check');

  // Curl preview should include real zone id and no encoded placeholder.
  const curlOut = page.locator('#curl-out');
  await expect(curlOut).toContainText(`/zones/${zoneId}/dns_records`);
  await expect(curlOut).not.toContainText('%7Bzone_id%7D');

  await page.locator('#send-btn').click();
  await expect(page.locator('#resp-bar')).toBeVisible({ timeout: 10_000 });
  await expect(page.locator('#resp-out')).not.toContainText('No route for that URI');
});
