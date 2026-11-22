/* K4b：主会话跑着时新建会话，两边各自回答；切回来历史不串 */
const { chromium } = require('playwright')
const { spawn } = require('node:child_process')
const http = require('node:http')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const PORT = 5140
const FAKE = 5197
const ROOT = process.env.SPIRIT_SOURCE || path.resolve(__dirname, '..', '..', 'spirit')
const PY = process.env.SPIRIT_PY || path.resolve(__dirname, '..', '..', '.venv', 'Scripts', 'python.exe')

const home = fs.mkdtempSync(path.join(os.tmpdir(), 'spirit-mui-home-'))
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'spirit-mui-work-'))

function check(ok, label) {
  if (!ok) throw new Error(`FAIL ${label}`)
  console.log(`ok ${label}`)
}

const fake = http.createServer((req, res) => {
  let body = ''
  req.on('data', (chunk) => { body += chunk })
  req.on('end', () => {
    let text = ''
    try {
      const payload = JSON.parse(body || '{}')
      const last = (payload.messages || []).filter((m) => m.role === 'user').pop()
      text = String(last?.content || '')
    } catch { /* ignore */ }
    const answer = text.includes('B') ? '答B' : '答A'
    setTimeout(() => {
      const chunks = [
        { id: 'x', object: 'chat.completion.chunk', created: 1, model: 'fake-model',
          choices: [{ index: 0, delta: { role: 'assistant', content: answer }, finish_reason: null }] },
        { id: 'x', object: 'chat.completion.chunk', created: 1, model: 'fake-model',
          choices: [{ index: 0, delta: {}, finish_reason: 'stop' }],
          usage: { prompt_tokens: 4, completion_tokens: 2, total_tokens: 6 } },
      ]
      const data = chunks.map((c) => `data: ${JSON.stringify(c)}\n\n`).join('')
        + 'data: [DONE]\n\n'
      res.writeHead(200, { 'Content-Type': 'text/event-stream' })
      res.end(data)
    }, 1500)
  })
})

const engine = spawn(PY, ['-m', 'MoBo.main', 'web'], {
  cwd: ROOT,
  env: {
    ...process.env,
    SPIRIT_HOME: home,
    SPIRIT_WORKDIR: work,
    SPIRIT_SESSION_DIR: home,
    SPIRIT_WEB_PORT: String(PORT),
    SPIRIT_WEB_AUTH: '0',
    PYTHONIOENCODING: 'utf-8',
    NO_PROXY: '127.0.0.1,localhost',
    no_proxy: '127.0.0.1,localhost',
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

;(async () => {
  await new Promise((resolve) => fake.listen(FAKE, '127.0.0.1', resolve))
  await waitReady()
  const browser = await chromium.launch({ channel: 'msedge' })
  const page = await browser.newPage({ viewport: { width: 1400, height: 950 } })
  const errors = []
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()) })
  page.on('pageerror', (e) => errors.push(String(e)))

  await page.goto(`http://127.0.0.1:${PORT}/?desktop=1`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(800)
  const setup = await page.evaluate(async () => {
    const post = (url, body) => fetch(url, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then((r) => r.json())
    const saved = await post('/api/provider', {
      name: 'FakeMulti', kind: 'openai-chat',
      base_url: 'http://127.0.0.1:5197/v1', models: ['fake-model'], api_key: 'k',
    })
    const active = await post('/api/provider/active', { id: saved.provider.id, model: 'fake-model' })
    return { saved: saved.ok, active: active.ok }
  })
  check(setup.saved && setup.active, 'fake provider active')

  // 1. 主会话发 A（模型 1.5s 后才回）
  await page.fill('#input', 'A')
  await page.click('#send')
  await page.waitForTimeout(250)

  // 2. 主会话还在跑时点“新对话” → 应该开独立会话，不 409
  const [newResponse] = await Promise.all([
    page.waitForResponse((r) => r.url().endsWith('/api/session') && r.request().method() === 'POST'),
    page.click('#newSession'),
  ])
  const newData = await newResponse.json()
  check(newData.ok && newData.session && newData.session !== 'primary',
    `new session created ${JSON.stringify(newData)}`)
  await page.waitForTimeout(300)
  check((await page.locator('.assistantBody').count()) === 0, 'new session blank')

  // 3. 新会话发 B，拿到 B 的回答
  let sentSession = ''
  page.on('request', (request) => {
    if (request.url().endsWith('/api/send')) {
      try { sentSession = request.postDataJSON().session } catch { /* ignore */ }
    }
  })
  await page.fill('#input', 'B')
  await page.click('#send')
  await page.waitForTimeout(200)
  check(sentSession === newData.session, `send routed to runtime: ${sentSession}`)
  await page.waitForFunction(
    () => document.querySelector('.column')?.textContent.includes('答B'),
    null, { timeout: 15000 },
  )
  check((await page.locator('.column').innerText()).includes('答B'), 'runtime answered B')

  // 4. 等两个会话都落盘，切回主会话看 A
  let sessions = []
  const deadline = Date.now() + 15000
  while (Date.now() < deadline) {
    sessions = await page.evaluate(() => fetch('/api/sessions').then((r) => r.json()))
    if (sessions.length >= 2) break
    await page.waitForTimeout(200)
  }
  const primary = sessions.find((item) => item.session === 'primary')
  const secondary = sessions.find((item) => item.session !== 'primary')
  check(primary && secondary && primary.path !== secondary.path,
    `two session files ${JSON.stringify(sessions)}`)
  await page.click(`.session-item[data-path="${primary.path.replace(/\\/g, '\\\\')}"]`)
  await page.waitForFunction(
    () => document.querySelector('.column')?.textContent.includes('答A'),
    null, { timeout: 15000 },
  )
  check(!(await page.locator('.column').innerText()).includes('答B'), 'primary shows its own A')

  // 5. 再切回额外会话看 B
  await page.click(`.session-item[data-path="${secondary.path.replace(/\\/g, '\\\\')}"]`)
  await page.waitForFunction(
    () => document.querySelector('.column')?.textContent.includes('答B'),
    null, { timeout: 15000 },
  )
  check(!(await page.locator('.column').innerText()).includes('答A'), 'secondary shows its own B')
  check(errors.length === 0, `console errors ${errors.slice(0, 2).join(' | ')}`)

  await browser.close()
  console.log('\nMULTISESSION UI OK')
})().catch((err) => {
  console.error(err)
  process.exitCode = 1
}).finally(async () => {
  try { engine.kill() } catch { /* ignore */ }
  try { fake.close() } catch { /* ignore */ }
  await new Promise((r) => setTimeout(r, 300))
  process.exit(process.exitCode || 0)
})
