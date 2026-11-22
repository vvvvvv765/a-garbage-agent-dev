const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, colorScheme: 'light' });
  page.on('pageerror', (err) => console.log('[pageerror]', err.message));
  page.on('console', (msg) => { if (msg.type() === 'error') console.log('[console]', msg.text()); });

  await page.goto('http://127.0.0.1:5000/', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(900);
  await page.screenshot({ path: 'tupian/spirit_v2_home.png' });

  await page.click('#searchBtn');
  await page.waitForTimeout(200);
  await page.click('#modelPill');
  await page.waitForTimeout(250);
  await page.screenshot({ path: 'tupian/spirit_v2_popover.png' });
  await page.keyboard.press('Escape');

  await page.click('#accountBtn');
  await page.waitForTimeout(300);
  await page.screenshot({ path: 'tupian/spirit_v2_settings.png' });
  await page.click('#closeSettings');
  await page.waitForTimeout(200);

  await page.fill('#input', '只回复两个字：收到');
  await page.press('#input', 'Enter');
  await page.waitForTimeout(7000);
  await page.screenshot({ path: 'tupian/spirit_v2_chat.png' });

  await page.click('#tabTrail');
  await page.waitForTimeout(500);
  await page.screenshot({ path: 'tupian/spirit_v2_trail.png' });

  console.log('sessions:', await page.locator('.session-item').count());
  await browser.close();
})();
