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

  await page.fill('#input', '先读工作区的 README.md，再在 files/ 下新建 test.txt（内容 hello），不要自己猜。');
  await page.press('#input', 'Enter');

  await page.locator('.approvalCard').first().waitFor({ timeout: 90000 });
  console.log('warning:', await page.locator('.approvalWarning').innerText());
  console.log('card:', (await page.locator('.approvalCard').first().innerText()).slice(0, 220));
  await page.screenshot({ path: 'tupian/spirit_untrusted_approval.png' });

  await page.locator('.approvalCard').first().locator('.approvalActions button').first().click();
  await page.locator('.approvalCard[data-resolved="deny"]').first().waitFor({ timeout: 15000 });
  console.log('denied:', (await page.locator('.approvalCard').first().innerText()).slice(-80));
  await app.close();
})().catch((err) => {
  console.error('FAILED', err);
  process.exit(1);
});
