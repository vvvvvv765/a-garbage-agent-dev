/* 深度思考开关：模型浮层与设置页两处可改、双向同步、落盘到 config */
const { chromium } = require('playwright')
const { spawn } = require('node:child_process')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const PORT = 5113
const ROOT = process.env.SPIRIT_SOURCE || path.resolve(__dirname, '..', '..', 'spirit')
const PY = process.env.SPIRIT_PY || path.resolve(__dirname, '..', '..', '.venv', 'Scripts', 'python.exe')

const home = fs.mkdtempSync(path.join(os.tmpdir(), 'spirit-think-ui-'))
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'spirit-think-ui-work-'))

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

const apiSettings = () => fetch(`http://127.0.0.1:${PORT}/api/settings`).then((r) => r.json())

;(async () => {
  await waitReady()
  const browser = await chromium.launch({ channel: 'msedge' })
  const page = await browser.newPage({ viewport: { width: 1500, height: 950 } })
  const errors = []
  page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()) })
  page.on('pageerror', (err) => errors.push(String(err)))

  await page.goto(`http://127.0.0.1:${PORT}/?desktop=1`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(900)

  const popSwitch = page.locator('#popThinkingSwitch')
  const setSwitch = page.locator('#thinkingSwitch')

  // 1. 模型浮层：有开关，初始关闭
  await page.click('#modelPill')
  await page.waitForTimeout(250)
  check(await popSwitch.count() === 1, '模型浮层有深度思考开关')
  check(await popSwitch.getAttribute('aria-checked') === 'false', '浮层初始关闭')

  // 2. 浮层里打开 → 服务端收到
  await page.click('#popThinking')
  await page.waitForTimeout(500)
  check(await popSwitch.getAttribute('aria-checked') === 'true', '浮层切到开')
  let settings = await apiSettings()
  check(settings.thinking === true, '服务端 thinking=true')

  // 3. 设置页同步为开
  await page.keyboard.press('Escape')
  await page.click('#menuBtn')
  await page.click('#menuPop button[data-action="general-settings"]')
  await page.waitForTimeout(350)
  await page.click('.settings-nav-item[data-panel="model"]')
  await page.waitForTimeout(350)
  check(await setSwitch.getAttribute('aria-checked') === 'true', '设置页同步为开')

  // 3b. 思考档位是 DeepSeek 的 Low / High / Max
  const effortLabels = await page.locator('#effortSeg button').allInnerTexts()
  check(effortLabels.join(',') === 'Low,High,Max', `effort labels ${effortLabels}`)
  await page.click('#effortSeg button[data-value="max"]')
  await page.waitForTimeout(400)
  settings = await apiSettings()
  check(settings.effort === 'max', `服务端 effort=max: ${settings.effort}`)

  // 4. 设置页关闭 → 浮层同步为关
  await page.click('#thinkingSwitch')
  await page.waitForTimeout(500)
  check(await setSwitch.getAttribute('aria-checked') === 'false', '设置页切到关')
  settings = await apiSettings()
  check(settings.thinking === false, '服务端 thinking=false')
  await page.click('#closeSettings')
  await page.waitForTimeout(200)
  await page.click('#modelPill')
  await page.waitForTimeout(250)
  check(await popSwitch.getAttribute('aria-checked') === 'false', '浮层同步为关')

  // 5. 落盘：重启后读的 engine.thinking 跟着变（直接看配置文件）
  const configPath = path.join(home, 'config.json')
  const raw = JSON.parse(fs.readFileSync(configPath, 'utf8'))
  check(raw.engine.thinking === false, 'config.json 已落盘 engine.thinking=false')

  check(errors.length === 0, `console errors ${errors.length} ${errors.slice(0, 2).join(' | ')}`)
  await browser.close()
  console.log('\nTHINKING UI OK')
})().catch((err) => {
  console.error(err)
  process.exitCode = 1
}).finally(async () => {
  try { engine.kill() } catch { /* ignore */ }
  await new Promise((r) => setTimeout(r, 300))
  process.exit(process.exitCode || 0)
})
