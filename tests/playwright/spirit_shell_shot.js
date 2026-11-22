const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge' });
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 }, colorScheme: 'light' });
  page.on('pageerror', (err) => console.log('[pageerror]', err.message));
  page.on('console', (msg) => { if (msg.type() === 'error') console.log('[console]', msg.text()); });

  await page.goto('http://127.0.0.1:5000/', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1000);
  await page.screenshot({ path: 'tupian/spirit_shell_home.png' });

  await page.click('#accountBtn');
  await page.waitForTimeout(300);
  await page.screenshot({ path: 'tupian/spirit_shell_settings.png' });
  await page.click('#closeSettings');
  await page.waitForTimeout(200);

  await page.click('#modelPill');
  await page.waitForTimeout(300);
  await page.screenshot({ path: 'tupian/spirit_shell_popover.png' });
  await page.keyboard.press('Escape');

  await page.fill('#input', '用 bash 执行 echo spirit_ok，再简单解释一下你做了什么');
  await page.press('#input', 'Enter');
  await page.waitForTimeout(18000);
  await page.screenshot({ path: 'tupian/spirit_shell_chat.png' });

  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1200);
  await page.screenshot({ path: 'tupian/spirit_shell_sessions.png' });

  console.log('sessions:', await page.locator('.session-item').count());
  await browser.close();
})();
