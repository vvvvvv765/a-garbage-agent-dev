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

  // 自动审批 + 给当前提供商配价格，验证成本显示
  const configured = await page.evaluate(async () => {
    await fetch('/api/approval-mode', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mode: 'auto' }),
    });
    const data = await fetch('/api/providers').then((r) => r.json());
    const provider = data.providers.find((item) => item.active);
    const res = await fetch('/api/provider', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        id: provider.id,
        name: provider.name,
        base_url: provider.base_url,
        models: provider.models,
        pricing: { input: 2, output: 8, currency: 'CNY' },
      }),
    }).then((r) => r.json());
    return { provider: provider.name, ok: res.ok, reloaded: res.provider?.reloaded };
  });
  console.log('configured:', JSON.stringify(configured));

  // 从干净会话开始，避免上一轮 usage 让“非 0”断言提前通过
  await page.click('#newSession');
  await page.waitForTimeout(800);

  await page.fill('#input', '只回复两个字：收到');
  await page.press('#input', 'Enter');
  await page.locator('.assistantBody').first().waitFor({ timeout: 60000 });
  await page.waitForFunction(
    () => !document.getElementById('statTokens').textContent.startsWith('0 tok'),
    { timeout: 20000 },
  );
  await page.waitForTimeout(1200);
  console.log('statTokens:', await page.locator('#statTokens').innerText());
  console.log('statTokens title:', await page.locator('#statTokens').getAttribute('title'));
  console.log('statContext:', await page.locator('#statContext').innerText());
  const usage = await page.evaluate(() => fetch('/api/usage').then((r) => r.json()));
  console.log('usage:', JSON.stringify(usage.session), 'last:', JSON.stringify(usage.last));
  await page.screenshot({ path: 'tupian/spirit_usage_stats.png' });

  // Token 用量浮层
  await page.click('#tokenStat');
  await page.waitForSelector('#usagePop:not([hidden])');
  console.log('token pop:', (await page.locator('#usagePop').innerText()).replace(/\n/g, ' | '));
  await page.screenshot({ path: 'tupian/spirit_usage_pop.png' });
  await page.keyboard.press('Escape');
  await page.waitForTimeout(200);

  // 会话统计浮层
  await page.click('#turnStat');
  await page.waitForSelector('#turnPop:not([hidden])');
  console.log('turn pop:', (await page.locator('#turnPop').innerText()).replace(/\n/g, ' | '));
  await page.screenshot({ path: 'tupian/spirit_turn_pop.png' });
  await page.keyboard.press('Escape');
  await page.waitForTimeout(200);

  // 预算设置
  await page.click('#accountBtn');
  await page.fill('#limitTurnTokens', '5000');
  await page.dispatchEvent('#limitTurnTokens', 'change');
  await page.waitForTimeout(500);
  const settings = await page.evaluate(() => fetch('/api/settings').then((r) => r.json()));
  console.log('budget saved:', settings.max_turn_tokens);
  await page.fill('#limitTurnTokens', '0');
  await page.dispatchEvent('#limitTurnTokens', 'change');
  await page.waitForTimeout(300);

  await app.close();
})().catch((err) => {
  console.error('FAILED', err);
  process.exit(1);
});
