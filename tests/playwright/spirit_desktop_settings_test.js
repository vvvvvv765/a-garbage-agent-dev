const { _electron: electron } = require('playwright');
const fs = require('fs');
const os = require('os');
const path = require('path');

(async () => {
  const tempWorkspace = fs.mkdtempSync(path.join(os.tmpdir(), 'spirit-ui-ws-'));
  fs.writeFileSync(path.join(tempWorkspace, 'hello.txt'), 'hi');

  const packaged = process.env.SPIRIT_EXE;
  const app = await electron.launch(
    packaged
      ? { executablePath: packaged, args: [], timeout: 120000 }
      : {
          executablePath: path.resolve(__dirname, '..', '..', 'desktop', 'node_modules', 'electron', 'dist', 'electron.exe'),
          args: [path.resolve(__dirname, '..', '..', 'desktop')],
          timeout: 90000,
        },
  );
  const page = await app.firstWindow({ timeout: 90000 });
  page.on('pageerror', (err) => console.log('[pageerror]', err.message));
  page.on('console', (msg) => { if (msg.type() === 'error') console.log('[console]', msg.text()); });
  await page.waitForTimeout(1800);
  console.log('window title:', await page.title());

  // 设置 → 模型
  await page.click('#menuBtn');
  await page.click('#menuPop button[data-action="general-settings"]');
  await page.waitForTimeout(300);
  await page.click('.settings-nav-item[data-panel="model"]');
  await page.waitForSelector('.provider-row');
  console.log('providers:', await page.locator('.provider-row').count());
  console.log('provider row:', (await page.locator('.provider-row').first().innerText()).replace(/\n/g, ' | '));
  await page.screenshot({ path: 'tupian/spirit_ui_providers.png' });

  // 添加提供商：预设画廊 → 表单（上下文窗口在模型配置里设置）
  await page.click('#addProvider');
  await page.waitForSelector('.preset-card');
  console.log('presets:', await page.locator('.preset-card').count());
  await page.fill('#presetSearch', 'deepseek');
  await page.waitForTimeout(200);
  console.log('presets filtered:', await page.locator('.preset-card').count());
  await page.screenshot({ path: 'tupian/spirit_ui_provider_presets.png' });
  await page.click('.preset-card:has-text("DeepSeek")');
  await page.waitForSelector('#providerForm:not([hidden])');
  console.log('preset prefill:', await page.inputValue('#pfName'), await page.inputValue('#pfBaseUrl'), await page.inputValue('#pfKind'));
  console.log('context field visible:', await page.locator('#pfContextWindow').isVisible());
  await page.fill('#pfName', '测试提供商');
  await page.fill('#pfBaseUrl', 'https://example.com/v1');
  await page.fill('#pfKey', 'sk-demo-1234');
  await page.fill('#pfModels', 'demo-model, demo-model-2');
  await page.fill('#pfContextWindow', '64000');
  await page.click('#pfSave');
  await page.waitForTimeout(800);
  console.log('providers after add:', await page.locator('.provider-row').count());
  const savedProviders = await page.evaluate(() => fetch('/api/providers').then((r) => r.json()));
  const added = (savedProviders.providers || []).find((item) => item.name === '测试提供商');
  console.log('saved provider context:', added && added.context_window);
  await page.screenshot({ path: 'tupian/spirit_ui_provider_added.png' });

  // 关设置，确认方式菜单
  await page.click('#closeSettings');
  await page.click('#workdirChip');
  await page.waitForTimeout(250);
  await page.screenshot({ path: 'tupian/spirit_ui_approval_menu.png' });
  await page.click('#approvalPop button[data-mode="ask"]');
  await page.waitForTimeout(500);
  console.log('approval label:', await page.locator('#approvalLabel').innerText());
  const afterManual = await page.evaluate(() => fetch('/api/settings').then((r) => r.json()));
  console.log('settings approval:', afterManual.approval);
  await page.click('#workdirChip');
  await page.click('#approvalPop button[data-mode="auto"]');

  // 添加工作区（应用内输入框）
  await page.click('#addWorkspaceBtn');
  await page.fill('#promptInput', tempWorkspace);
  await page.click('#promptOk');
  await page.waitForTimeout(900);
  console.log('workspaces:', await page.locator('#workspaceList .ws-item').allInnerTexts());
  await page.locator('#workspaceList .ws-item').last().click();
  await page.waitForTimeout(900);
  const afterWorkspace = await page.evaluate(() => fetch('/api/settings').then((r) => r.json()));
  console.log('workdir:', afterWorkspace.workdir);
  console.log('expected:', tempWorkspace);
  await page.screenshot({ path: 'tupian/spirit_ui_workspace.png' });

  // 切回默认
  await page.locator('#workspaceList .ws-item').first().click();
  await page.waitForTimeout(700);
  console.log('back:', await page.evaluate(() => fetch('/api/settings').then((r) => r.json())).then((s) => s.workdir));

  // 模型浮层里换模型
  await page.click('#modelPill');
  await page.waitForTimeout(300);
  console.log('model options:', await page.locator('.pop-option').allInnerTexts());
  console.log('model groups:', await page.locator('.model-group').allInnerTexts());
  await page.screenshot({ path: 'tupian/spirit_ui_model_menu.png' });
  await page.locator('.pop-option', { hasText: 'deepseek-v4-flash' }).click();
  await page.waitForTimeout(900);
  const afterModel = await page.evaluate(() => fetch('/api/settings').then((r) => r.json()));
  console.log('model after select:', afterModel.model);
  await page.click('#popModel');
  await page.waitForTimeout(200);
  await page.locator('.pop-option', { hasText: 'deepseek-Flash' }).first().click();
  await page.waitForTimeout(700);
  console.log('model back:', await page.evaluate(() => fetch('/api/settings').then((r) => r.json())).then((s) => s.model));

  await app.close();
})().catch((err) => {
  console.error('FAILED', err);
  process.exit(1);
});
