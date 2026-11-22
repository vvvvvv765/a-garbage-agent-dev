/* 供应商界面改版验收：菜单 / 预设画廊 / OpenCode Go 预填 / 授权范围入口 */
const { chromium } = require('playwright')
const { spawn } = require('node:child_process')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const PORT = 5091
const ROOT = process.env.SPIRIT_SOURCE || path.resolve(__dirname, '..', '..', 'spirit')
const PY = process.env.SPIRIT_PY || path.resolve(__dirname, '..', '..', '.venv', 'Scripts', 'python.exe')
const SHOTS = path.join(os.tmpdir(), 'spirit-tupian')

const home = fs.mkdtempSync(path.join(os.tmpdir(), 'spirit-ui-home-'))
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'spirit-ui-work-'))

const engine = spawn(PY, ['-m', 'MoBo.main', 'web'], {
  cwd: ROOT,
  env: {
    ...process.env,
    SPIRIT_HOME: home,
    SPIRIT_WORKDIR: work,
    SPIRIT_WEB_PORT: String(PORT),
    SPIRIT_WEB_AUTH: '0', // 测试：关掉控制面令牌（鉴权由 spirit_web_auth_test 覆盖）
    PYTHONIOENCODING: 'utf-8',
    DEEPSEEK_API_KEY: 'sk-ui-test',
  },
  windowsHide: true,
})
engine.stdout.on('data', () => {})
engine.stderr.on('data', (d) => process.stderr.write(d))

async function waitReady() {
  for (let i = 0; i < 100; i += 1) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/api/status`, { signal: AbortSignal.timeout(800) })
      if (res.ok) return
    } catch { /* 还没起 */ }
    await new Promise((r) => setTimeout(r, 300))
  }
  throw new Error('engine not ready')
}

function check(ok, label) {
  if (!ok) throw new Error(`FAIL ${label}`)
  console.log(`ok ${label}`)
}

;(async () => {
  await waitReady()
  const browser = await chromium.launch({ channel: 'msedge' })
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
  const errors = []
  page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()) })
  page.on('pageerror', (err) => errors.push(String(err)))

  await page.goto(`http://127.0.0.1:${PORT}/?desktop=1`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1200)

  // 1. 菜单：大模型设置 / 通用设置
  await page.click('#menuBtn')
  const menuText = await page.locator('#menuPop').innerText()
  check(menuText.includes('大模型设置') && menuText.includes('通用设置'), 'menu items')

  await page.click('#menuPop button[data-action="model-settings"]')
  check(await page.locator('.settings-panel[data-panel="model"]').isVisible(), 'model panel opened')
  check(await page.locator('.settings-nav-item[data-panel="model"]').evaluate((el) => el.classList.contains('active')), 'nav active')

  // 2. 预设画廊
  await page.click('#addProvider')
  await page.waitForTimeout(300)
  const rail = await page.locator('#presetCats').innerText()
  check(rail.includes('全部') && rail.includes('模型厂商') && rail.includes('第三方平台') && rail.includes('本地'), 'category rail')
  const allCount = await page.locator('#presetCats .preset-cat').first().innerText()
  check(/\d+/.test(allCount), `all count ${allCount.replace(/\n/g, ' ')}`)
  const cards = await page.locator('#presetGrid .preset-card').count()
  check(cards > 100, `cards ${cards}`)
  const groups = await page.locator('#presetGrid .preset-group-title').count()
  check(groups >= 4, `groups ${groups}`)
  check(await page.locator('#presetCustom').isVisible(), 'custom card visible')

  // 3. 搜索 + OpenCode Go 预填
  await page.fill('#presetSearch', 'opencode')
  await page.waitForTimeout(200)
  const hits = await page.locator('#presetGrid .preset-card').count()
  check(hits >= 1 && hits < 10, `search hits ${hits}`)
  await page.locator('#presetGrid .preset-card', { hasText: 'OpenCode Go' }).first().click()
  await page.waitForTimeout(200)
  check(await page.locator('#providerForm').isVisible(), 'form opened')
  const base = await page.inputValue('#pfBaseUrl')
  check(base === 'https://opencode.ai/zen/go', `base url ${base}`)
  check(await page.inputValue('#pfKind') === 'anthropic', 'kind anthropic')
  check(await page.inputValue('#pfAuth') === 'key', 'auth key')
  check(await page.locator('#pfAuthRow').isVisible(), 'auth row visible')
  check(await page.locator('#pfKeyLink').isVisible(), 'api key link visible')
  check(!(await page.locator('#providerBehavior').isVisible()), 'behavior card hidden in form')
  await page.screenshot({ path: path.join(SHOTS, 'spirit_provider_opencode.png') })

  // 4. 返回 + 分类切换
  await page.click('#pfCancel')
  await page.click('#addProvider')
  await page.fill('#presetSearch', '')
  await page.locator('#presetCats .preset-cat', { hasText: '模型厂商' }).click()
  await page.waitForTimeout(200)
  const vendorGroups = await page.locator('#presetGrid .preset-group-title').allInnerTexts()
  check(vendorGroups.length === 1 && vendorGroups[0].includes('模型厂商'), 'single category filter')
  check(!(await page.locator('#providerBehavior').isVisible()), 'behavior card hidden in gallery')
  await page.screenshot({ path: path.join(SHOTS, 'spirit_provider_gallery.png') })

  // 5. 切渗透 → 场景浮层里有授权范围
  await page.click('#presetBack')
  await page.waitForTimeout(200)
  check(await page.locator('#providerBehavior').isVisible(), 'behavior card back on list')
  await page.screenshot({ path: path.join(SHOTS, 'spirit_provider_list.png') })
  await page.click('#closeSettings')
  await page.evaluate(async (port) => {
    await fetch(`http://127.0.0.1:${port}/api/scenario`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: 'pentest' }),
    })
  }, PORT)
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1200)
  await page.click('#scenarioChip')
  const popText = await page.locator('#scenarioPop').innerText()
  check(popText.includes('授权范围'), 'scope entry in scenario pop')
  await page.screenshot({ path: path.join(SHOTS, 'spirit_scenario_scope.png') })

  // 6. 侧栏底部没有“本地用户”
  check(!(await page.locator('aside.sidebar').innerText()).includes('本地用户'), 'account row removed')

  check(errors.length === 0, `console errors ${errors.length} ${errors.slice(0, 3).join(' | ')}`)

  await browser.close()
  console.log('\nPROVIDER UI V2 OK')
})().catch(async (err) => {
  console.error(err)
  process.exitCode = 1
}).finally(async () => {
  try { engine.kill() } catch { /* ignore */ }
  await new Promise((r) => setTimeout(r, 300))
  process.exit(process.exitCode || 0)
})
