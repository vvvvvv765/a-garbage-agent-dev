/* 会话级场景界面：会话开始后另一个变灰；新会话解锁；加载会话时同步 */
const { chromium } = require('playwright')
const { spawn } = require('node:child_process')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const PORT = 5094
const ROOT = process.env.SPIRIT_SOURCE || path.resolve(__dirname, '..', '..', 'spirit')
const PY = process.env.SPIRIT_PY || path.resolve(__dirname, '..', '..', '.venv', 'Scripts', 'python.exe')
const SHOTS = path.join(os.tmpdir(), 'spirit-tupian')

const home = fs.mkdtempSync(path.join(os.tmpdir(), 'spirit-lock-home-'))
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'spirit-lock-work-'))

// 预置一份"渗透"会话（有记录 + sidecar），启动后应自动恢复并锁定
const sessions = path.join(home, 'Session_Storage')
fs.mkdirSync(sessions, { recursive: true })
const sessionFile = path.join(sessions, 'session-20260101-000000.jsonl')
fs.writeFileSync(sessionFile, JSON.stringify({
  seq: 1, address: 'user', payload: '你好',
}) + '\n', 'utf-8')
fs.writeFileSync(sessionFile + '.meta.json', JSON.stringify({ scenario: 'pentest' }), 'utf-8')

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
  const page = await browser.newPage({ viewport: { width: 1500, height: 950 } })
  const errors = []
  // 锁定后切换按 409 返回，浏览器记成资源错误 —— 这是预期的一步
  page.on('console', (msg) => {
    if (msg.type() === 'error' && !msg.text().includes('409 (CONFLICT)')) errors.push(msg.text())
  })
  page.on('pageerror', (err) => errors.push(String(err)))

  await page.goto(`http://127.0.0.1:${PORT}/?desktop=1`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1200)

  // 启动恢复了渗透会话：chip 显示渗透
  check((await page.locator('#scenarioLabel').innerText()).includes('渗透'), 'restored scenario chip')

  await page.click('#scenarioChip')
  await page.waitForTimeout(200)
  const daily = page.locator('#scenarioPop .scenario-option', { hasText: '日常' }).first()
  const pentest = page.locator('#scenarioPop .scenario-option', { hasText: '渗透' }).first()
  check(await daily.evaluate((el) => el.classList.contains('disabled')), 'daily greyed out')
  check(await pentest.evaluate((el) => el.classList.contains('active')), 'pentest active')
  const hint = await page.locator('#scenarioPop .menu-hint').innerText()
  check(hint.includes('锁定'), `hint locked ${hint}`)
  await daily.click()
  await page.waitForTimeout(300)
  const toastText = await page.locator('#toast').innerText().catch(() => '')
  check(toastText.includes('不能再切换'), `locked toast ${toastText}`)
  await page.screenshot({ path: path.join(SHOTS, 'spirit_scenario_locked.png') })

  // 新会话 → 解锁
  await page.click('#scenarioPop')
  await page.click('#newSession')
  await page.waitForTimeout(800)
  await page.click('#scenarioChip')
  await page.waitForTimeout(200)
  const daily2 = page.locator('#scenarioPop .scenario-option', { hasText: '日常' }).first()
  check(!(await daily2.evaluate((el) => el.classList.contains('disabled'))), 'new session unlocks')
  const hint2 = await page.locator('#scenarioPop .menu-hint').innerText()
  check(hint2.includes('开局前'), `hint unlocked ${hint2}`)
  await page.screenshot({ path: path.join(SHOTS, 'spirit_scenario_unlocked.png') })

  check(errors.length === 0, `console errors ${errors.length} ${errors.slice(0, 2).join(' | ')}`)

  await browser.close()
  console.log('\nSCENARIO LOCK UI OK')
})().catch(async (err) => {
  console.error(err)
  process.exitCode = 1
}).finally(async () => {
  try { engine.kill() } catch { /* ignore */ }
  await new Promise((r) => setTimeout(r, 300))
  process.exit(process.exitCode || 0)
})
