const { _electron: electron } = require('playwright');
const fs = require('fs');
const path = require('path');

(async () => {
  const app = await electron.launch({
    executablePath: path.resolve(__dirname, '..', '..', 'desktop', 'release', 'Spirit', 'Spirit.exe'),
    args: [],
    timeout: 120000,
  });
  app.on('console', (msg) => console.log('[electron]', msg.type(), msg.text()));

  const page = await app.firstWindow({ timeout: 120000 });
  page.on('pageerror', (err) => console.log('[pageerror]', err.message));
  page.on('console', (msg) => { if (msg.type() === 'error') console.log('[console]', msg.text()); });

  await page.waitForTimeout(2000);
  console.log('title:', await page.title());
  console.log('url:', page.url());
  const settings = await page.evaluate(() => fetch('/api/settings').then((r) => r.json()));
  console.log('settings:', JSON.stringify(settings));
  const usage = await page.evaluate(() => fetch('/api/usage').then((r) => r.json()));
  console.log('usage:', JSON.stringify(usage.session), 'budgets:', JSON.stringify(usage.budgets));
  const scenarios = await page.evaluate(() => fetch('/api/scenarios').then((r) => r.json()));
  console.log('scenarios:', JSON.stringify(scenarios));
  const workspace = path.resolve(__dirname, '..', '..', 'desktop', 'release', 'Spirit', 'workspace');
  for (const folder of ['scripts', 'files', 'images', 'videos', 'audio', 'tmp']) {
    if (!fs.existsSync(path.join(workspace, folder))) {
      throw new Error(`workspace folder missing: ${folder}`);
    }
  }
  console.log('workspace folders: ok');
  console.log('sessions:', await page.locator('.session-item').count());
  await page.screenshot({ path: 'tupian/spirit_desktop_packaged.png' });

  await app.close();
})().catch((err) => {
  console.error('FAILED', err);
  process.exit(1);
});
