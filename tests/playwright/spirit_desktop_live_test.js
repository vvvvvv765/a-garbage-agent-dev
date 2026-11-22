const path = require('node:path')
const { _electron: electron } = require('playwright');

(async () => {
  const app = await electron.launch({
    executablePath: path.resolve(__dirname, '..', '..', 'desktop', 'release', 'Spirit', 'Spirit.exe'),
    args: [],
    timeout: 120000,
  });
  const page = await app.firstWindow({ timeout: 120000 });
  page.on('pageerror', (err) => console.log('[pageerror]', err.message));
  await page.waitForTimeout(1200);

  await page.fill('#input', '只回复两个字：收到');
  await page.press('#input', 'Enter');
  await page.locator('.assistantBody').first().waitFor({ timeout: 120000 });
  await page.waitForTimeout(800);
  console.log('assistant:', (await page.locator('.assistantBody').first().innerText()).slice(0, 120));
  await page.screenshot({ path: 'tupian/spirit_desktop_live.png' });
  await app.close();
})().catch((err) => {
  console.error('FAILED', err);
  process.exit(1);
});
