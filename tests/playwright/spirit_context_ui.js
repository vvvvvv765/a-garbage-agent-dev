const path = require('node:path')
const { _electron: electron } = require('playwright');

(async () => {
  const app = await electron.launch({
    executablePath: path.resolve(__dirname, '..', '..', 'desktop', 'node_modules', 'electron', 'dist', 'electron.exe'),
    args: [path.resolve(__dirname, '..', '..', 'desktop')],
    timeout: 90000,
  });
  const page = await app.firstWindow({ timeout: 90000 });
  page.on('pageerror', (err) => console.log('[pageerror]', err.message));
  await page.waitForTimeout(1600);

  await page.evaluate(() => fetch('/api/approval-mode', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: 'auto' }),
  }));

  await page.fill('#input', '只回复两个字：收到');
  await page.press('#input', 'Enter');
  await page.locator('.assistantBody').first().waitFor({ timeout: 60000 });
  await page.waitForTimeout(1200);

  await page.click('#contextStat');
  await page.waitForTimeout(600);
  console.log('total:', await page.locator('#ctxTotal').innerText());
  console.log('percent:', await page.locator('#ctxPercent').innerText());
  console.log('rows:', await page.locator('.ctx-row').allInnerTexts());
  console.log('bar widths:', await page.evaluate(() => [
    document.getElementById('ctxBarSystem').style.width,
    document.getElementById('ctxBarTools').style.width,
    document.getElementById('ctxBarMessages').style.width,
  ]));
  await page.screenshot({ path: 'tupian/spirit_context_pop.png' });

  await app.close();
})().catch((err) => {
  console.error('FAILED', err);
  process.exit(1);
});
