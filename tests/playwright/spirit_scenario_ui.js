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

  console.log('chip:', await page.locator('#scenarioLabel').innerText());
  await page.click('#scenarioChip');
  await page.waitForTimeout(300);
  console.log('options:', (await page.locator('#scenarioPop .scenario-option').allInnerTexts()).map((t) => t.replace(/\n/g, ' | ')));
  await page.screenshot({ path: 'tupian/spirit_scenario_menu.png' });

  await page.locator('#scenarioPop .scenario-option', { hasText: '渗透' }).click();
  await page.waitForFunction(
    () => document.getElementById('scenarioLabel').textContent.includes('渗透'),
    { timeout: 10000 },
  );
  await page.waitForTimeout(500);
  const settings = await page.evaluate(() => fetch('/api/settings').then((r) => r.json()));
  console.log('after switch:', await page.locator('#scenarioLabel').innerText(), '| settings:', settings.scenario);
  await page.screenshot({ path: 'tupian/spirit_scenario_pentest.png' });

  await page.click('#scenarioChip');
  await page.locator('#scenarioPop .scenario-option', { hasText: '日常' }).click();
  await page.waitForFunction(
    () => document.getElementById('scenarioLabel').textContent.includes('日常'),
    { timeout: 10000 },
  );
  console.log('back:', await page.locator('#scenarioLabel').innerText());

  await app.close();
})().catch((err) => {
  console.error('FAILED', err);
  process.exit(1);
});
