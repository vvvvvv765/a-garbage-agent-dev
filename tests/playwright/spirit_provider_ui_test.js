const path = require('node:path')
const { _electron: electron } = require('playwright');
const http = require('http');

(async () => {
  const server = http.createServer((req, res) => {
    if (req.url === '/v1/models') {
      const body = JSON.stringify({ data: [{ id: 'demo-a' }, { id: 'demo-b' }] });
      res.writeHead(200, { 'Content-Type': 'application/json' });
      res.end(body);
      return;
    }
    res.writeHead(404);
    res.end('{}');
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;

  const app = await electron.launch({
    executablePath: path.resolve(__dirname, '..', '..', 'desktop', 'node_modules', 'electron', 'dist', 'electron.exe'),
    args: [path.resolve(__dirname, '..', '..', 'desktop')],
    timeout: 90000,
  });
  const page = await app.firstWindow({ timeout: 90000 });
  page.on('pageerror', (err) => console.log('[pageerror]', err.message));
  page.on('console', (msg) => { if (msg.type() === 'error') console.log('[console]', msg.text()); });
  page.on('dialog', (dialog) => dialog.accept());
  await page.waitForTimeout(1800);

  await page.click('#accountBtn');
  await page.click('.settings-nav-item[data-panel="model"]');
  await page.waitForSelector('.provider-row');

  // Anthropic 预设（只检查预填，不保存）
  await page.click('#addProvider');
  await page.waitForSelector('.preset-card');
  await page.fill('#presetSearch', 'claude');
  await page.waitForTimeout(200);
  console.log('claude presets:', await page.locator('.preset-card').count());
  await page.click('.preset-card:has-text("Claude（Anthropic）")');
  await page.waitForSelector('#providerForm:not([hidden])');
  console.log('anthropic prefill:', await page.inputValue('#pfKind'), await page.inputValue('#pfBaseUrl'), await page.inputValue('#pfModels'));
  await page.click('#pfCancel');
  await page.waitForTimeout(300);

  // 自定义 Chat 预设
  await page.click('#addProvider');
  await page.waitForSelector('.preset-card');
  await page.fill('#presetSearch', 'custom');
  await page.waitForTimeout(200);
  await page.click('.preset-card:has-text("自定义 OpenAI Chat")');
  await page.waitForSelector('#providerForm:not([hidden])');
  console.log('kind:', await page.inputValue('#pfKind'));

  await page.fill('#pfName', '本地测试');
  await page.fill('#pfBaseUrl', `http://127.0.0.1:${port}/v1`);
  await page.fill('#pfKey', 'sk-local');
  await page.click('#pfFetchModels');
  await page.waitForSelector('.model-option');
  const options = await page.locator('.model-option').allInnerTexts();
  console.log('fetched models:', options);
  await page.locator('.model-option').first().click();
  console.log('models input:', await page.inputValue('#pfModels'));
  await page.screenshot({ path: 'tupian/spirit_provider_fetch.png' });

  await page.click('#pfSave');
  await page.waitForTimeout(900);
  const row = page.locator('.provider-row:has-text("本地测试")');
  console.log('row:', (await row.innerText()).replace(/\n/g, ' | '));
  console.log('rows:', await page.locator('.provider-row').count());

  // 清理：编辑 → 删除（非当前，可删）
  await row.locator('button:has-text("编辑")').click();
  await page.waitForSelector('#providerForm:not([hidden])');
  await page.click('#pfDelete');
  await page.waitForTimeout(900);
  console.log('rows after delete:', await page.locator('.provider-row').count());

  await app.close();
  server.close();
})().catch((err) => {
  console.error('FAILED', err);
  process.exit(1);
});
