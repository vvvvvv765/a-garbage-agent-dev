const { chromium } = require('playwright');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge' });

  const light = await browser.newPage({ viewport: { width: 1280, height: 900 }, colorScheme: 'light' });
  await light.goto('http://127.0.0.1:5000/', { waitUntil: 'domcontentloaded' });
  await light.waitForTimeout(600);
  await light.screenshot({ path: 'tupian/spirit_shell_light.png' });

  const dark = await browser.newPage({ viewport: { width: 1280, height: 900 }, colorScheme: 'dark' });
  await dark.goto('http://127.0.0.1:5000/', { waitUntil: 'domcontentloaded' });
  await dark.waitForTimeout(600);
  await dark.screenshot({ path: 'tupian/spirit_shell_dark.png' });

  console.log('shots ok');
  await browser.close();
})();
