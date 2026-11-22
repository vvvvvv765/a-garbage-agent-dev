/* 端到端：假模型端点按 150ms/段吐思考与正文，看页面是不是边收边画 */
const { chromium } = require('playwright')
const { spawn } = require('node:child_process')
const http = require('node:http')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const PORT = 5124
const FAKE_PORT = 5199
const ROOT = process.env.SPIRIT_SOURCE || path.resolve(__dirname, '..', '..', 'spirit')
const PY = process.env.SPIRIT_PY || path.resolve(__dirname, '..', '..', '.venv', 'Scripts', 'python.exe')

const home = fs.mkdtempSync(path.join(os.tmpdir(), 'spirit-e2e-home-'))
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'spirit-e2e-work-'))

function check(ok, label) {
  if (!ok) throw new Error(`FAIL ${label}`)
  console.log(`ok ${label}`)
}

/* ---------- 假 Anthropic 端点 ---------- */
const fake = http.createServer((req, res) => {
  if (req.method !== 'POST' || !req.url.includes('/v1/messages')) {
    res.writeHead(404)
    res.end()
    return
  }
  req.on('data', () => {})
  req.on('end', () => {
    res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' })
    const send = (type, data) => res.write(`event: ${type}\ndata: ${JSON.stringify({ type, ...data })}\n\n`)
    send('message_start', {
      message: {
        id: 'msg_fake', type: 'message', role: 'assistant', model: 'fake-model',
        content: [], stop_reason: null,
        usage: { input_tokens: 10, output_tokens: 1 },
      },
    })
    send('content_block_start', { index: 0, content_block: { type: 'thinking', thinking: '' } })
    let i = 0
    const thinkTimer = setInterval(() => {
      i += 1
      send('content_block_delta', { index: 0, delta: { type: 'thinking_delta', thinking: `想${i}` } })
      if (i < 10) return
      clearInterval(thinkTimer)
      send('content_block_delta', { index: 0, delta: { type: 'signature_delta', signature: 'sig-fake' } })
      send('content_block_stop', { index: 0 })
      send('content_block_start', { index: 1, content_block: { type: 'text', text: '' } })
      let j = 0
      const textTimer = setInterval(() => {
        j += 1
        send('content_block_delta', { index: 1, delta: { type: 'text_delta', text: `答${j}` } })
        if (j < 20) return
        clearInterval(textTimer)
        send('content_block_stop', { index: 1 })
        send('message_delta', { delta: { stop_reason: 'end_turn' }, usage: { output_tokens: 30 } })
        send('message_stop', {})
        res.end()
      }, 150)
    }, 150)
  })
})

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

async function post(url, body) {
  return fetch(`http://127.0.0.1:${PORT}${url}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).then((r) => r.json())
}

;(async () => {
  await new Promise((resolve) => fake.listen(FAKE_PORT, '127.0.0.1', resolve))
  await waitReady()

  const provider = await post('/api/provider', {
    name: 'FakeStream',
    kind: 'anthropic',
    auth: 'key',
    base_url: `http://127.0.0.1:${FAKE_PORT}`,
    models: ['fake-model'],
    api_key: 'test-key',
  })
  check(provider.ok, '假提供商已保存')
  const active = await post('/api/provider/active', { id: 'fakestream', model: 'fake-model' })
  check(active.ok, '假提供商已启用')

  const browser = await chromium.launch({ channel: 'msedge' })
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } })
  await page.goto(`http://127.0.0.1:${PORT}/?desktop=1`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(800)

  await page.fill('#input', '你好')
  await page.click('#send')

  const timeline = []
  const started = Date.now()
  for (let i = 0; i < 120; i += 1) {
    const snap = await page.evaluate(() => {
      const body = document.querySelector('.reasoningBlock .r-body')
      const details = document.querySelector('.reasoningBlock')
      const md = document.querySelector('.assistantBody .markdownBody')
      return {
        reasoning: body ? body.textContent.length : 0,
        open: details ? details.open : null,
        text: md ? md.textContent.length : 0,
      }
    })
    timeline.push({ t: Date.now() - started, ...snap })
    if (snap.text >= 40 && snap.open === false) break
    await page.waitForTimeout(100)
  }

  console.log('timeline sample:', timeline.filter((_, i) => i % 5 === 0).slice(0, 20))
  await page.waitForTimeout(1200)   // 等这一轮收尾，日志尾部才写得进去

  const firstThink = timeline.find((x) => x.reasoning > 0)
  const firstText = timeline.find((x) => x.text > 0)
  const textSnaps = timeline.filter((x) => x.text > 0)
  const distinctText = [...new Set(textSnaps.map((x) => x.text))]
  const textSpan = textSnaps.length > 1 ? textSnaps[textSnaps.length - 1].t - textSnaps[0].t : 0
  const final = timeline[timeline.length - 1]

  check(!!firstThink && firstThink.reasoning > 0, '思考先出现')
  check(!!firstText && firstThink.t < firstText.t, '思考先于正文')
  check(distinctText.length >= 3, `正文分段上屏（${distinctText.length} 个长度）`)
  check(textSpan >= 300, `正文跨时 ${textSpan}ms 持续渲染`)
  check(final.text >= 40, `正文完成 ${final.text} 字`)
  check(final.open === false, '思考块结束时折叠')

  await browser.close()
  console.log('\nTHINKING STREAM E2E OK')
})().catch((err) => {
  console.error(err)
  process.exitCode = 1
}).finally(async () => {
  try { engine.kill() } catch { /* ignore */ }
  try { fake.close() } catch { /* ignore */ }
  await new Promise((r) => setTimeout(r, 300))
  process.exit(process.exitCode || 0)
})
