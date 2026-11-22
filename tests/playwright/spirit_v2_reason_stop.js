const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge' });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, colorScheme: 'light' });
  page.on('pageerror', (err) => console.log('[pageerror]', err.message));

  await page.goto('http://127.0.0.1:5000/', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(700);

  const settings = await page.evaluate(async () => {
    const res = await fetch('/api/settings', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ thinking: true, effort: 'high' }),
    });
    return res.json();
  });
  console.log('settings:', settings);

  await page.fill('#input', '请先逐步推理，再回答：17*23*31 等于多少？只给结果');
  await page.press('#input', 'Enter');
  await page.waitForTimeout(25000);
  console.log('reasoning blocks:', await page.locator('.reasoningBlock').count());
  console.log('final:', await page.locator('.turnHead').last().textContent());
  await page.screenshot({ path: 'tupian/spirit_v2_reasoning.png' });

  await page.fill('#input', '写一篇 800 字的故事，分三段');
  await page.press('#input', 'Enter');
  await page.waitForTimeout(1500);
  await page.click('#send');
  await page.waitForTimeout(5000);
  const heads = await page.locator('.turnHead').allTextContents();
  console.log('turn heads:', heads);
  await page.screenshot({ path: 'tupian/spirit_v2_interrupt.png' });

  await browser.close();
})();
