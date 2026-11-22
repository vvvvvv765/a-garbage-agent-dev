const path = require('node:path')
const { _electron: electron } = require('playwright');
const fs = require('fs');

(async () => {
  const bash = path.resolve(__dirname, '..', '..', 'desktop', 'release', 'Spirit', 'resources', 'engine', '_internal', 'shell', 'PortableGit', 'bin', 'bash.exe');
  if (!fs.existsSync(bash)) throw new Error('bundled bash missing');
  console.log('bundled bash: ok');

  const app = await electron.launch({
    executablePath: path.resolve(__dirname, '..', '..', 'desktop', 'release', 'Spirit', 'Spirit.exe'),
    args: [],
    timeout: 120000,
  });
  const page = await app.firstWindow({ timeout: 120000 });
  page.on('pageerror', (err) => console.log('[pageerror]', err.message));
  await page.waitForTimeout(1600);

  await page.evaluate(() => fetch('/api/approval-mode', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ mode: 'auto' }),
  }));

  await page.fill('#input', '用 bash 执行 echo packaged_shell_ok，不要自己猜结果。');
  await page.press('#input', 'Enter');
  await page.locator('.assistantBody').first().waitFor({ timeout: 90000 });
  await page.waitForTimeout(1200);

  const column = await page.locator('#column').innerText();
  console.log('shell output visible:', column.includes('packaged_shell_ok'));
  console.log('assistant:', (await page.locator('.assistantBody').first().innerText()).slice(0, 80));
  await page.screenshot({ path: 'tupian/spirit_packaged_shell.png' });
  await app.close();
})().catch((err) => {
  console.error('FAILED', err);
  process.exit(1);
});
