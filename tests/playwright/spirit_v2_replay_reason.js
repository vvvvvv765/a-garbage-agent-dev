const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, colorScheme: 'light' });
  page.on('pageerror', (e) => console.log('[pageerror]', e.message));
  await page.goto('http://127.0.0.1:5000/', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1200);
  const items = page.locator('.session-item');
  const count = await items.count();
  console.log('sessions:', count);
  for (let i = 0; i < count; i++) {
    const title = await items.nth(i).locator('.title').textContent();
    if (title.includes('推理') || title.includes('目录')) {
      console.log('open:', title);
      await items.nth(i).click();
      break;
    }
  }
  await page.waitForTimeout(1200);
  console.log('reasoning blocks:', await page.locator('.reasoningBlock').count());
  await page.screenshot({ path: 'tupian/spirit_v2_reasoning.png' });
  await browser.close();
})();
