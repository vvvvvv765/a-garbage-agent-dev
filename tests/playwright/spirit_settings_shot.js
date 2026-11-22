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
  await page.waitForTimeout(1500);
  await page.click('#accountBtn');
  await page.waitForTimeout(500);
  await page.screenshot({ path: 'tupian/spirit_settings_general.png' });
  console.log('sandbox switch:', await page.locator('#sandboxSwitch').getAttribute('aria-checked'));
  console.log('limits:', await page.locator('#limitTurnTokens').inputValue(), await page.locator('#repeatLimit').inputValue());
  await app.close();
})().catch((err) => {
  console.error('FAILED', err);
  process.exit(1);
});
