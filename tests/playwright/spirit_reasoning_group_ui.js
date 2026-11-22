/* 思考合并：一轮只留一个折叠块；CPU 还在跑时轮次头不能提前变“已完成” */
const { chromium } = require('playwright')
const { spawn } = require('node:child_process')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const PORT = 5129
const ROOT = process.env.SPIRIT_SOURCE || path.resolve(__dirname, '..', '..', 'spirit')
const PY = process.env.SPIRIT_PY || path.resolve(__dirname, '..', '..', '.venv', 'Scripts', 'python.exe')

const home = fs.mkdtempSync(path.join(os.tmpdir(), 'spirit-reason-home-'))
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'spirit-reason-work-'))

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

;(async () => {
  await waitReady()
  const browser = await chromium.launch({ channel: 'msedge' })
  const page = await browser.newPage({ viewport: { width: 1400, height: 950 } })
  const errors = []
  page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()) })
  page.on('pageerror', (err) => errors.push(String(err)))

  await page.addInitScript(() => {
    const Original = window.EventSource
    window.__sources = []
    window.EventSource = class extends Original {
      constructor(url, options) {
        super(url, options)
        window.__sources.push(this)
      }
    }
  })
  await page.route('**/api/send', (route) => route.fulfill({
    status: 200, contentType: 'application/json', body: '{"ok":true}',
  }))
  await page.goto(`http://127.0.0.1:${PORT}/?desktop=1`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(900)
  await page.evaluate(() => document.querySelector('.shell').classList.remove('hero'))

  const emit = (events) => page.evaluate((items) => {
    const source = window.__sources[0]
    for (const item of items) {
      source.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(item) }))
    }
  }, events)

  // 真的走一次发送，让前端 startTurn 建轮次头
  await page.fill('#input', '测试思考合并')
  await page.press('#input', 'Enter')
  await page.waitForTimeout(400)
  check(await page.locator('.turnHead').count() === 1, 'turn head created')

  // 之后的内核状态由测试控制：先保持“还在跑”
  await page.evaluate(() => {
    window.__turnActive = true
    const original = window.fetch.bind(window)
    window.fetch = (input, init) => {
      const url = String(input)
      const fake = (body) => Promise.resolve(new Response(JSON.stringify(body), {
        status: 200, headers: { 'Content-Type': 'application/json' },
      }))
      if (url.includes('/api/kernel')) return fake({ cpu: { turn_active: window.__turnActive } })
      if (url.includes('/api/running')) return fake({ calls: [] })
      return original(input, init)
    }
  })

  await emit([{ type: 'reasoning_delta', text: '第一段：先看看工作区。' }])
  await page.waitForTimeout(800)
  let headPhase = await page.locator('.turnHead').innerText()
  check(headPhase.includes('思考中') && headPhase.includes('字'), `thinking phase: ${headPhase}`)

  await emit([
    { type: 'reasoning_end' },
    { type: 'tool_call', call_id: 'r1', name: 'list_dir', arguments: '{"path":"."}' },
  ])
  await page.waitForTimeout(800)
  headPhase = await page.locator('.turnHead').innerText()
  check(headPhase.includes('执行工具') && headPhase.includes('0/1'), `tool phase: ${headPhase}`)

  await emit([{ type: 'tool_result', call_id: 'r1', name: 'list_dir', content: 'files' }])
  await page.waitForTimeout(300)
  await emit([
    { type: 'reasoning_delta', text: '第二段：再检查渲染。' },
    { type: 'reasoning_end' },
    { type: 'assistant_delta', text: '检查完了。' },
    { type: 'assistant_end' },
  ])
  await page.waitForTimeout(500)

  const blocks = page.locator('.reasoningBlock')
  check(await blocks.count() === 1, 'one reasoning block for the turn')
  check((await blocks.first().locator('summary').innerText()).includes('2 段'), 'reasoning summary counts segments')
  const body = await blocks.first().locator('.r-body').evaluate((el) => el.textContent)
  check(body.includes('第一段') && body.includes('第二段'), 'both reasoning segments kept')
  check(await blocks.first().evaluate((el) => el.open) === false, 'reasoning folded after thinking')

  // 同一轮第二段正文不再重复 “Spirit” 标签
  await emit([
    { type: 'assistant_delta', text: '补充一句。' },
    { type: 'assistant_end' },
  ])
  await page.waitForTimeout(300)
  const bodies = page.locator('.assistantBody')
  check(await bodies.count() >= 2, `assistant bodies ${await bodies.count()}`)
  const last = bodies.last()
  check((await last.getAttribute('class') || '').includes('continued'), 'second body marked continued')
  const marker = await last.evaluate((el) => getComputedStyle(el, '::before').content)
  check(marker === 'none' || marker === 'normal', `continued label hidden: ${marker}`)

  // 800ms 空闲收尾时内核仍在跑：不能显示已完成
  await page.waitForTimeout(1300)
  const headText = await page.locator('.turnHead').innerText()
  check(!headText.includes('已完成'), `turn head not finished while CPU active: ${headText}`)

  await page.evaluate(() => { window.__turnActive = false })
  await page.waitForFunction(
    () => document.querySelector('.turnHead')?.textContent.includes('已完成'),
    null,
    { timeout: 8000 },
  )
  console.log('ok turn head finishes after CPU idle')
  const breakdown = await page.locator('.turnHead').getAttribute('title')
  check(breakdown && breakdown.includes('总') && breakdown.includes('思考'), `breakdown: ${breakdown}`)
  check(errors.length === 0, `console errors ${errors.slice(0, 2).join(' | ')}`)

  await browser.close()
  console.log('\nREASONING GROUP UI OK')
})().catch((err) => {
  console.error(err)
  process.exitCode = 1
}).finally(async () => {
  try { engine.kill() } catch { /* ignore */ }
  await new Promise((r) => setTimeout(r, 300))
  process.exit(process.exitCode || 0)
})
