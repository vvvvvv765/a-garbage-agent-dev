const path = require('node:path')
const { _electron: electron } = require('playwright');

(async () => {
  const app = await electron.launch({
    executablePath: path.resolve(__dirname, '..', '..', 'desktop', 'node_modules', 'electron', 'dist', 'electron.exe'),
    args: [path.resolve(__dirname, '..', '..', 'desktop')],
    timeout: 90000,
  });
  app.on('console', (msg) => console.log('[electron]', msg.type(), msg.text()));

  const page = await app.firstWindow({ timeout: 90000 });
  page.on('pageerror', (err) => console.log('[pageerror]', err.message));
  page.on('console', (msg) => { if (msg.type() === 'error') console.log('[console]', msg.text()); });

  await page.waitForTimeout(2000);
  console.log('title:', await page.title());
  console.log('url:', page.url());
  console.log('sessions:', await page.locator('.session-item').count());
  console.log('input:', await page.locator('#input').count());
  await page.screenshot({ path: 'tupian/spirit_desktop.png' });

  await app.close();
})().catch((err) => {
  console.error('FAILED', err);
  process.exit(1);
});
