const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, colorScheme: 'light' });
  page.on('pageerror', (err) => console.log('[pageerror]', err.message));
  page.on('console', (msg) => { if (msg.type() === 'error') console.log('[console]', msg.text()); });

  await page.goto('http://127.0.0.1:5000/', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(900);

  const prompt = '现在用 bash 执行 echo spirit_approval_ok，然后告诉我输出，不要自己猜。';

  // 第一轮：拒绝
  await page.fill('#input', prompt);
  await page.press('#input', 'Enter');
  await page.locator('.approvalCard').first().waitFor({ timeout: 120000 });
  await page.waitForTimeout(300);
  await page.screenshot({ path: 'tupian/spirit_approval_card.png' });
  console.log('approval card:', (await page.locator('.approvalCard').first().innerText()).slice(0, 200));

  await page.locator('.approvalCard').first().locator('.approvalActions button').first().click();
  await page.locator('.approvalCard[data-resolved="deny"]').first().waitFor({ timeout: 15000 });
  await page.waitForTimeout(1200);
  await page.screenshot({ path: 'tupian/spirit_approval_denied.png' });
  console.log('denied card:', (await page.locator('.approvalCard').first().innerText()).slice(0, 200));

  // 等第一轮结束（出现已完成的轮次头）
  await page.locator('.turnHead[data-done="1"]').last().waitFor({ timeout: 120000 });
  await page.waitForTimeout(500);

  // 第二轮：允许
  await page.fill('#input', prompt);
  await page.press('#input', 'Enter');
  await page.locator('.approvalCard:not([data-resolved])').first().waitFor({ timeout: 120000 });
  await page.waitForTimeout(300);
  await page.locator('.approvalCard:not([data-resolved])').first().locator('.approvalActions .approve').click();
  await page.waitForTimeout(1000);
  await page.screenshot({ path: 'tupian/spirit_approval_allowed.png' });

  await page.locator('.turnHead[data-done="1"]').last().waitFor({ timeout: 120000 });
  await page.waitForTimeout(800);
  await page.screenshot({ path: 'tupian/spirit_approval_allowed_done.png' });

  const text = await page.locator('#column').innerText();
  console.log('has ok output:', text.includes('spirit_approval_ok'));
  console.log('cards:', await page.locator('.approvalCard').count());
  await browser.close();
})();
