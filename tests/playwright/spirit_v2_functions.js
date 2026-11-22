const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, colorScheme: 'light' });
  page.on('pageerror', (err) => console.log('[pageerror]', err.message));

  let dialogText = '改名测试';
  page.on('dialog', async (dialog) => {
    if (dialog.type() === 'prompt') await dialog.accept(dialogText);
    else await dialog.accept();
  });

  await page.goto('http://127.0.0.1:5000/', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(800);

  // 先产生一个会话
  await page.fill('#input', '只回复两个字：收到');
  await page.press('#input', 'Enter');
  await page.waitForTimeout(9000);

  // 会话重命名 / 删除
  await page.hover('.session-item');
  await page.click('.session-more');
  await page.waitForTimeout(200);
  await page.click('.session-menu button:nth-child(1)');
  await page.waitForTimeout(900);
  console.log('after rename:', await page.locator('.session-item .title').first().textContent());

  // 开启深度思考
  await page.evaluate(async () => {
    await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ thinking: true, effort: 'low' }),
    });
  });

  // 思考显示
  await page.fill('#input', '先推理再回答：17 乘 23 等于多少？只给结果');
  await page.press('#input', 'Enter');
  await page.waitForTimeout(18000);
  console.log('reasoning blocks:', await page.locator('.reasoningBlock').count());
  await page.screenshot({ path: 'tupian/spirit_v2_reasoning.png' });

  // 中断
  await page.fill('#input', '写一篇 800 字的故事，分三段');
  await page.press('#input', 'Enter');
  await page.waitForTimeout(1500);
  await page.click('#send');
  await page.waitForTimeout(4000);
  const heads = await page.locator('.turnHead').allTextContents();
  console.log('turn heads:', heads);
  await page.screenshot({ path: 'tupian/spirit_v2_interrupt.png' });

  // 删除
  await page.hover('.session-item');
  await page.click('.session-more');
  await page.waitForTimeout(200);
  await page.click('.session-menu button:nth-child(2)');
  await page.waitForTimeout(900);
  console.log('sessions after delete:', await page.locator('.session-item').count());

  await browser.close();
})();
