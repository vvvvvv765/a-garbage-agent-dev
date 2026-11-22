const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge' });
  const page = await browser.newPage({
    viewport: { width: 1280, height: 900 },
    colorScheme: 'light',
  });
  page.on('console', (msg) => console.log('[page]', msg.type(), msg.text()));
  page.on('pageerror', (err) => console.log('[pageerror]', err.message));

  await page.goto('http://127.0.0.1:5000/', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);
  await page.screenshot({ path: 'tupian/spirit_ui_empty.png' });

  await page.fill('#input', '用 bash 执行 echo spirit_ok，再简单解释一下你做了什么');
  await page.press('#input', 'Enter');

  await page.waitForTimeout(20000);
  await page.screenshot({ path: 'tupian/spirit_ui_chat.png', fullPage: false });

  const text = await page.textContent('#column');
  console.log('column text:', (text || '').slice(0, 300));
  await browser.close();
})();
