/* 供应商体系（照抄 cc-switch）界面验收：搜索 / 表单新字段 / 测试 / 测速 / 图标 / 导入导出 / 拖拽排序 */
const { chromium } = require('playwright')
const { spawn } = require('node:child_process')
const http = require('node:http')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const PORT = 5092
const FAKE_PORT = 5093
const ROOT = process.env.SPIRIT_SOURCE || path.resolve(__dirname, '..', '..', 'spirit')
const PY = process.env.SPIRIT_PY || path.resolve(__dirname, '..', '..', '.venv', 'Scripts', 'python.exe')
const SHOTS = path.join(os.tmpdir(), 'spirit-tupian')

const home = fs.mkdtempSync(path.join(os.tmpdir(), 'spirit-ui-home-'))
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'spirit-ui-work-'))

// 本地假端点：测试连接 / 测速用，避免真网络抖动
const fake = http.createServer((req, res) => {
  res.writeHead(200, { 'Content-Type': 'application/json' })
  res.end('{"ok":true}')
})
fake.listen(FAKE_PORT, '127.0.0.1')

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

async function openModelPanel(page) {
  await page.click('#menuBtn')
  await page.click('#menuPop button[data-action="model-settings"]')
  await page.waitForTimeout(300)
}

;(async () => {
  await waitReady()
  const browser = await chromium.launch({ channel: 'msedge' })
  const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } })
  const errors = []
  // 「余额不支持」按 400 返回，浏览器会把它记成资源错误 —— 这是预期的一步，不算 JS 异常
  page.on('console', (msg) => {
    if (msg.type() === 'error' && !msg.text().includes('400 (BAD REQUEST)')) errors.push(msg.text())
  })
  page.on('pageerror', (err) => errors.push(String(err)))

  await page.goto(`http://127.0.0.1:${PORT}/?desktop=1`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1200)

  // ---------- 1. 列表工具栏 ----------
  await openModelPanel(page)
  check(await page.locator('#providerSearch').isVisible(), 'search visible')
  check(await page.locator('#providerExport').isVisible(), 'export visible')
  check(await page.locator('#providerImport').isVisible(), 'import visible')

  // ---------- 2. 添加供应商：新字段 ----------
  await page.click('#addProvider')
  await page.fill('#presetSearch', 'deepseek')
  await page.waitForTimeout(200)
  await page.locator('#presetGrid .preset-card', { hasText: 'DeepSeek' }).first().click()
  await page.waitForTimeout(200)
  check(await page.locator('#pfCategory').isVisible(), 'category field')
  check(await page.locator('#pfEndpoints').isVisible(), 'endpoints field')
  check(await page.locator('#pfNotes').isVisible(), 'notes field')
  check(await page.locator('#pfWebsite').isVisible(), 'website field')
  check(await page.locator('#pfIconPick').isVisible(), 'icon picker button')
  check(await page.locator('#pfPriceCached').isVisible(), 'cached price field')
  check(await page.locator('#pfCurrency').isVisible(), 'currency field')
  check(await page.locator('#pfContextWindow').isVisible(), 'context window field')
  check(await page.locator('#pfMaxTokens').isVisible(), 'max tokens field')
  const prefilledBase = await page.inputValue('#pfBaseUrl')
  const endpointsText = await page.inputValue('#pfEndpoints')
  check(endpointsText.includes(prefilledBase), `endpoints prefilled ${endpointsText}`)

  // 改成本地假端点，便于测试连接 / 测速
  await page.fill('#pfName', 'UI 测试供应商')
  await page.fill('#pfBaseUrl', `http://127.0.0.1:${FAKE_PORT}`)
  await page.fill('#pfEndpoints', [`http://127.0.0.1:${FAKE_PORT}`, `http://127.0.0.1:${FAKE_PORT}/backup`].join('\n'))
  await page.fill('#pfModels', 'm1')
  await page.fill('#pfKey', 'sk-ui-provider')
  await page.fill('#pfNotes', '备注：本地假端点')
  await page.selectOption('#pfCategory', 'third_party')

  // 图标选择器
  await page.click('#pfIconPick')
  await page.waitForTimeout(200)
  check(await page.locator('#iconMask').isVisible(), 'icon mask opened')
  const iconCells = await page.locator('#iconGrid .icon-cell').count()
  check(iconCells > 20, `icon cells ${iconCells}`)
  await page.locator('#iconGrid .icon-cell').first().click()
  await page.waitForTimeout(150)
  check(await page.locator('#pfIconPreview img').count() === 1, 'icon preview image')

  // 测试连接
  await page.click('#pfCheck')
  await page.waitForTimeout(800)
  const checkText = await page.locator('#pfSpeedResult').innerText()
  check(checkText.includes('可达'), `check result ${checkText}`)

  // 测速
  await page.click('#pfSpeedTest')
  await page.waitForTimeout(1500)
  const speedRows = await page.locator('#pfSpeedList .speed-item').count()
  check(speedRows === 2, `speed rows ${speedRows}`)
  check(await page.locator('#pfSpeedList .speed-item.best').count() === 1, 'best marked')
  await page.screenshot({ path: path.join(SHOTS, 'spirit_provider_system_form.png') })

  // 保存
  await page.click('#pfSave')
  await page.waitForTimeout(900)
  check(await page.locator('#providerListView').isVisible(), 'back to list after save')

  // ---------- 3. 列表：分类徽章 / 备注 / 测试按钮 ----------
  const row = page.locator('.provider-row', { hasText: 'UI 测试供应商' }).first()
  check(await row.count() === 1, 'row created')
  const rowText = await row.innerText()
  check(rowText.includes('备注：本地假端点'), 'notes shown as url line')
  check(rowText.includes('第三方'), 'category chip')
  await row.locator('button', { hasText: '测试' }).click()
  await page.waitForTimeout(800)
  const badge = await page.locator('.provider-row', { hasText: 'UI 测试供应商' }).first().locator('.provider-health').innerText()
  check(badge.includes('可达'), `health badge ${badge}`)

  // ---------- 4. 搜索 ----------
  await page.fill('#providerSearch', 'UI 测试')
  await page.waitForTimeout(200)
  check(await page.locator('.provider-row').count() === 1, 'search filters list')
  await page.fill('#providerSearch', 'no-such-provider')
  await page.waitForTimeout(200)
  check(await page.locator('.provider-empty').isVisible(), 'search empty state')
  await page.fill('#providerSearch', '')
  await page.waitForTimeout(200)

  // ---------- 5. 导出 / 导入 ----------
  await page.click('#providerExport')
  await page.waitForTimeout(600)
  const exported = await page.inputValue('#providerIoText')
  check(exported.includes('spirit-providers') && exported.includes('UI 测试供应商'), 'export json')
  await page.click('#providerIoCancel')

  await page.click('#providerImport')
  await page.fill('#providerIoText', JSON.stringify({
    providers: [{ id: 'ui-import', name: 'UI 导入供应商', base_url: 'http://127.0.0.1:5093', models: ['m'], api_key: 'sk-import' }],
  }))
  await page.click('#providerIoOk')
  await page.waitForTimeout(800)
  check(await page.locator('.provider-row', { hasText: 'UI 导入供应商' }).count() === 1, 'imported row visible')

  // ---------- 6. 拖拽排序 ----------
  const before = await page.evaluate(async (port) => {
    const data = await fetch(`http://127.0.0.1:${port}/api/providers`).then((r) => r.json())
    return data.providers.map((item) => item.id)
  }, PORT)
  const firstRow = page.locator('.provider-row').first()
  const secondRow = page.locator('.provider-row').nth(1)
  await firstRow.dragTo(secondRow)
  await page.waitForTimeout(800)
  const after = await page.evaluate(async (port) => {
    const data = await fetch(`http://127.0.0.1:${port}/api/providers`).then((r) => r.json())
    return data.providers.map((item) => item.id)
  }, PORT)
  check(after[0] === before[1] && after[1] === before[0], `drag reorder ${before.slice(0, 2)} -> ${after.slice(0, 2)}`)
  await page.screenshot({ path: path.join(SHOTS, 'spirit_provider_system_list.png') })

  // ---------- 7. 余额（本地假端点 → 不支持，前端提示） ----------
  const balanceRow = page.locator('.provider-row', { hasText: 'UI 测试供应商' }).first()
  await balanceRow.locator('button', { hasText: '余额' }).click()
  await page.waitForTimeout(600)
  const toastText = await page.locator('#toast').innerText().catch(() => '')
  check(toastText.includes('没有内置的余额查询') || toastText.includes('余额查询失败'), `balance toast ${toastText}`)

  check(errors.length === 0, `console errors ${errors.length} ${errors.slice(0, 3).join(' | ')}`)

  await browser.close()
  console.log('\nPROVIDER SYSTEM UI OK')
})().catch(async (err) => {
  console.error(err)
  process.exitCode = 1
}).finally(async () => {
  try { engine.kill() } catch { /* ignore */ }
  try { fake.close() } catch { /* ignore */ }
  await new Promise((r) => setTimeout(r, 300))
  process.exit(process.exitCode || 0)
})
