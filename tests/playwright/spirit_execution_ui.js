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

  await page.evaluate(() => fetch('/api/approval-mode', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: 'auto' }),
  }));

  await page.fill('#input', '用 bash 执行 sleep 15，不要自己改命令，跑完告诉我。');
  await page.press('#input', 'Enter');

  const head = page.locator('.turnHead').first();
  await page.waitForFunction(
    () => [...document.querySelectorAll('.turnHead')].some((el) => el.textContent.includes('bash')),
    { timeout: 40000 },
  );
  console.log('turn head while running:', await head.innerText());
  await page.screenshot({ path: 'tupian/spirit_execution_running.png' });

  const started = Date.now();
  await page.click('#send');
  await page.waitForFunction(
    () => [...document.querySelectorAll('.turnHead')].some((el) => el.dataset.done === '1' && el.textContent.includes('已停止')),
    { timeout: 10000 },
  );
  console.log('stopped in ms:', Date.now() - started);
  console.log('turn head after stop:', await head.innerText());
  const running = await page.evaluate(() => fetch('/api/running').then((r) => r.json()));
  console.log('running after stop:', JSON.stringify(running));
  await page.screenshot({ path: 'tupian/spirit_execution_stopped.png' });

  await app.close();
})().catch((err) => {
  console.error('FAILED', err);
  process.exit(1);
});
