const path = require('node:path')
/* Electron 桌面壳 + 假 Anthropic 端点：页面是否边收边画（时间线） */
const { _electron: electron } = require('playwright')
const http = require('node:http')

const FAKE_PORT = 5199
const DESKTOP = path.resolve(__dirname, '..', '..', 'desktop')
const ELECTRON = `${DESKTOP}/node_modules/electron/dist/electron.exe`

function check(ok, label) {
  if (!ok) throw new Error(`FAIL ${label}`)
  console.log(`ok ${label}`)
}

const fake = http.createServer((req, res) => {
  if (req.method !== 'POST' || !req.url.includes('/v1/messages')) {
    res.writeHead(404)
    res.end()
    return
  }
  req.on('data', () => {})
  req.on('end', () => {
    const t0 = Date.now()
    console.log('fake request', req.url)
    res.writeHead(200, { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' })
    const send = (type, data) => res.write(`event: ${type}\ndata: ${JSON.stringify({ type, ...data })}\n\n`)
    send('message_start', {
      message: {
        id: 'msg_fake', type: 'message', role: 'assistant', model: 'fake-model',
        content: [], stop_reason: null, usage: { input_tokens: 10, output_tokens: 1 },
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
        console.log('fake stream done in', Date.now() - t0, 'ms')
      }, 150)
    }, 150)
  })
})

;(async () => {
  await new Promise((resolve) => fake.listen(FAKE_PORT, '127.0.0.1', resolve))
  const app = await electron.launch({ executablePath: ELECTRON, args: [DESKTOP], timeout: 90000 })
  const page = await app.firstWindow({ timeout: 90000 })
  page.on('pageerror', (err) => console.log('[pageerror]', err.message))
  await page.waitForTimeout(1800)

  const setup = await page.evaluate(async () => {
    const post = (url, body) => fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then((r) => r.json())
    const saved = await post('/api/provider', {
      name: 'FakeStream', kind: 'anthropic', auth: 'key',
      base_url: 'http://127.0.0.1:5199', models: ['fake-model'], api_key: 'test-key',
    })
    const active = await post('/api/provider/active', { id: 'fakestream', model: 'fake-model' })
    return { saved: saved.ok, active: active.ok }
  })
  check(setup.saved && setup.active, '假提供商已启用')

  const base = await page.evaluate(() => ({
    assistants: document.querySelectorAll('.assistantBody').length,
    reasonings: document.querySelectorAll('.reasoningBlock').length,
  }))
  await page.fill('#input', '你好')
  await page.click('#send')

  const timeline = []
  const started = Date.now()
  for (let i = 0; i < 120; i += 1) {
    const snap = await page.evaluate((baseline) => {
      const heads = document.querySelectorAll('.turnHead')
      const head = heads.length ? heads[heads.length - 1] : null
      const blocks = document.querySelectorAll('.reasoningBlock')
      const details = blocks.length > baseline.reasonings ? blocks[blocks.length - 1] : null
      const body = details ? details.querySelector('.r-body') : null
      const bodies = document.querySelectorAll('.assistantBody .markdownBody')
      const md = bodies.length > baseline.assistants ? bodies[bodies.length - 1] : null
      return {
        reasoning: body ? body.textContent.length : 0,
        open: details ? details.open : null,
        text: md ? md.textContent.length : 0,
        head: head ? head.textContent : null,
        done: head ? head.dataset.done === '1' : false,
        headCount: heads.length,
      }
    }, base)
    timeline.push({ t: Date.now() - started, ...snap })
    if (snap.done && snap.text > 0) break
    await page.waitForTimeout(100)
  }

  console.log('timeline sample:', timeline.filter((_, i) => i % 5 === 0).slice(0, 26))

  const firstThink = timeline.find((x) => x.reasoning > 0)
  const firstText = timeline.find((x) => x.text > 0)
  const textSnaps = timeline.filter((x) => x.text > 0)
  const distinctText = [...new Set(textSnaps.map((x) => x.text))]
  const textSpan = textSnaps.length > 1 ? textSnaps[textSnaps.length - 1].t - textSnaps[0].t : 0
  const final = timeline[timeline.length - 1]

  console.log({ firstThink, firstText, distinct: distinctText.length, textSpan, finalHead: final.head })
  check(!!firstThink, '思考出现')
  check(!!firstText && firstThink.t < firstText.t, '思考先于正文')
  check(distinctText.length >= 3, `正文分段（${distinctText.length} 段）`)
  check(textSpan >= 300, `正文跨时 ${textSpan}ms`)
  check(final.head && final.head.includes('已完成'), `轮次头收尾：${final.head}`)

  // 清理假提供商
  await page.evaluate(() => fetch('/api/provider', {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id: 'fakestream' }),
  }))
  await app.close()
  console.log('\nELECTRON STREAM TEST OK')
})().catch((err) => {
  console.error(err)
  process.exitCode = 1
}).finally(() => {
  try { fake.close() } catch { /* ignore */ }
  setTimeout(() => process.exit(process.exitCode || 0), 300)
})
