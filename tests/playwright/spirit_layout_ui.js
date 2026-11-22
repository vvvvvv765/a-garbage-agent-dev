/* 布局：对话列宽/居中、侧栏可拖动、工作区外访问开关 */
const { chromium } = require('playwright')
const { spawn } = require('node:child_process')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const PORT = 5102
const ROOT = process.env.SPIRIT_SOURCE || path.resolve(__dirname, '..', '..', 'spirit')
const PY = process.env.SPIRIT_PY || path.resolve(__dirname, '..', '..', '.venv', 'Scripts', 'python.exe')

const home = fs.mkdtempSync(path.join(os.tmpdir(), 'spirit-layout-home-'))
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'spirit-layout-work-'))

const engine = spawn(PY, ['-m', 'MoBo.main', 'web'], {
  cwd: ROOT,
  env: {
    ...process.env,
    SPIRIT_HOME: home,
    SPIRIT_WORKDIR: work,
    SPIRIT_WEB_PORT: String(PORT),
    SPIRIT_WEB_AUTH: '0',
    PYTHONIOENCODING: 'utf-8',
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
    } catch { /* wait */ }
    await new Promise((r) => setTimeout(r, 300))
  }
  throw new Error('engine not ready')
}

function check(ok, label) {
  if (!ok) throw new Error(`FAIL ${label}`)
  console.log(`ok ${label}`)
}

async function box(page, selector) {
  return page.locator(selector).boundingBox()
}

;(async () => {
  await waitReady()
  const browser = await chromium.launch({ channel: 'msedge' })
  const page = await browser.newPage({ viewport: { width: 1700, height: 1000 } })
  const errors = []
  page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()) })
  page.on('pageerror', (err) => errors.push(String(err)))

  await page.goto(`http://127.0.0.1:${PORT}/?desktop=1`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1000)
  await page.evaluate(() => document.querySelector('.shell').classList.remove('hero'))
  await page.waitForTimeout(200)

  // 对话列：用满中间区域并居中
  const main = await box(page, '.main')
  const column = await box(page, '.column')
  check(column.width >= 1000, `column width ${column.width}`)
  const leftGap = column.x - main.x
  const rightGap = (main.x + main.width) - (column.x + column.width)
  check(Math.abs(leftGap - rightGap) < 30, `column centered ${leftGap}/${rightGap}`)

  // 侧栏拖动 + 记忆
  const resizer = await box(page, '#sidebarResizer')
  const before = (await box(page, '.sidebar')).width
  await page.mouse.move(resizer.x + resizer.width / 2, resizer.y + 200)
  await page.mouse.down()
  await page.mouse.move(resizer.x + resizer.width / 2 + 120, resizer.y + 200, { steps: 8 })
  await page.mouse.up()
  await page.waitForTimeout(200)
  const after = (await box(page, '.sidebar')).width
  check(after > before + 80, `sidebar resized ${before} -> ${after}`)
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(800)
  const restored = (await box(page, '.sidebar')).width
  check(Math.abs(restored - after) < 6, `sidebar width persisted ${restored}`)
  const resizer2 = await box(page, '#sidebarResizer')
  await page.mouse.dblclick(resizer2.x + resizer2.width / 2, resizer2.y + 200)
  await page.waitForTimeout(200)
  check(Math.abs((await box(page, '.sidebar')).width - 258) < 3, 'sidebar reset on double click')

  // 旧沙箱设置已移除，通用设置里只留说明
  await page.click('#menuBtn')
  await page.click('#menuPop button[data-action="general-settings"]')
  await page.waitForTimeout(300)
  check(await page.locator('#sandboxSwitch').count() === 0, 'sandbox switch removed')
  check(await page.locator('#outsideSwitch').count() === 0, 'outside switch removed')
  check((await page.locator('.settings-panel[data-panel="general"]').innerText()).includes('不可信内容之后'),
    'settings still healthy')
  await page.click('#closeSettings')
  await page.waitForTimeout(200)

  // 范围菜单里的「工作区外访问」开关
  await page.click('#accessChip')
  await page.waitForTimeout(150)
  check((await page.locator('#outsideAutoState').innerText()) === '自动允许', 'outside auto default on')
  await page.locator('#accessPop button[data-outside-auto]').click()
  await page.waitForTimeout(400)
  let settings = await fetch(`http://127.0.0.1:${PORT}/api/settings`).then((r) => r.json())
  check(settings.sandbox_workspace === true, `workspace boundary on ${settings.sandbox_workspace}`)
  check((await page.locator('#outsideAutoState').innerText()) === '仅工作区', 'outside auto off label')
  if (await page.locator('#accessPop').isHidden()) await page.click('#accessChip')
  await page.locator('#accessPop button[data-outside-auto]').click()
  await page.waitForTimeout(400)
  settings = await fetch(`http://127.0.0.1:${PORT}/api/settings`).then((r) => r.json())
  check(settings.sandbox_workspace === false, `workspace boundary off ${settings.sandbox_workspace}`)
  await page.keyboard.press('Escape')
  await page.waitForTimeout(100)

  // 硬盘面板：五个区域 + 清理入口
  await page.click('#menuBtn')
  await page.click('#menuPop button[data-action="general-settings"]')
  await page.waitForTimeout(250)
  await page.click('.settings-nav-item[data-panel="disk"]')
  await page.waitForTimeout(500)
  check(await page.locator('#diskAreaList .path-row').count() === 7, 'disk areas listed')
  const diskText = await page.locator('#diskAreaList').innerText()
  for (const name of ['工作区', '能力产物', '会话', '日志', '沙箱', '上传', '项目资产']) {
    check(diskText.includes(name), `disk area ${name}`)
  }
  const diskApi = await fetch(`http://127.0.0.1:${PORT}/api/disk`).then((r) => r.json())
  check(diskApi.ok && /artifacts$/i.test(diskApi.areas.artifacts.path), 'disk api')
  page.on('dialog', (dialog) => dialog.accept())
  await page.click('#diskAreaList .path-row[data-area="artifacts"] button:has-text("清理")')
  await page.waitForTimeout(400)
  check(await page.locator('#diskAreaList .path-row').count() === 7, 'disk panel after clear')
  await page.click('#closeSettings')
  await page.waitForTimeout(200)

  check(errors.length === 0, `console errors ${errors.length} ${errors.slice(0, 2).join(' | ')}`)
  await browser.close()
  console.log('\nLAYOUT UI OK')
})().catch((err) => {
  console.error(err)
  process.exitCode = 1
}).finally(async () => {
  try { engine.kill() } catch { /* ignore */ }
  await new Promise((r) => setTimeout(r, 300))
  process.exit(process.exitCode || 0)
})
