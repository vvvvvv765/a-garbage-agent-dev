/* 真实浏览器下的本地控制面：页面拿令牌能用；不带令牌的 HTTP 调用被拒 */
const { chromium } = require('playwright')
const { spawn } = require('node:child_process')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const PORT = 5096
const ROOT = process.env.SPIRIT_SOURCE || path.resolve(__dirname, '..', '..', 'spirit')
const PY = process.env.SPIRIT_PY || path.resolve(__dirname, '..', '..', '.venv', 'Scripts', 'python.exe')

const home = fs.mkdtempSync(path.join(os.tmpdir(), 'spirit-authb-home-'))
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'spirit-authb-work-'))

// 注意：不设 SPIRIT_WEB_AUTH=0 —— 这里就是要验证鉴权开着时页面还能用
const engine = spawn(PY, ['-m', 'MoBo.main', 'web'], {
  cwd: ROOT,
  env: {
    ...process.env,
    SPIRIT_HOME: home,
    SPIRIT_WORKDIR: work,
    SPIRIT_WEB_PORT: String(PORT),
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
  const html = await fetch(`http://127.0.0.1:${PORT}/`).then((r) => r.text())
  const token = (html.match(/name="spirit-api-token" content="([^"]+)"/) || [])[1] || ''
  check(!!token, 'page carries token')

  const noToken = await fetch(`http://127.0.0.1:${PORT}/api/providers`)
  check(noToken.status === 401, `no token -> ${noToken.status}`)
  const withToken = await fetch(`http://127.0.0.1:${PORT}/api/providers`, {
    headers: { 'X-Spirit-Token': token },
  })
  check(withToken.status === 200, `with token -> ${withToken.status}`)

  const browser = await chromium.launch({ channel: 'msedge' })
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } })
  const errors = []
  page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()) })
  page.on('pageerror', (err) => errors.push(String(err)))
  await page.goto(`http://127.0.0.1:${PORT}/?desktop=1`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)

  // 页面初始化会拉 settings / sessions / providers，全部走页面 fetch 包装的令牌
  check((await page.locator('#modelPillText').innerText()).length > 0, 'page loaded model pill')
  await page.click('#menuBtn')
  await page.click('#menuPop button[data-action="model-settings"]')
  await page.waitForTimeout(600)
  check(await page.locator('.settings-panel[data-panel="model"]').isVisible(), 'settings opened (authed fetch)')
  check(errors.filter((e) => !e.includes('401')).length === 0, `console errors ${errors.slice(0, 2).join(' | ')}`)

  await browser.close()
  console.log('\nAUTH BROWSER OK')
})().catch(async (err) => {
  console.error(err)
  process.exitCode = 1
}).finally(async () => {
  try { engine.kill() } catch { /* ignore */ }
  await new Promise((r) => setTimeout(r, 300))
  process.exit(process.exitCode || 0)
})
