/* 工具行渲染：call_id 匹配、结果预览、折叠/展开、失败自动展开、异常可折叠 */
const { chromium } = require('playwright')
const { spawn } = require('node:child_process')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const PORT = 5101
const ROOT = process.env.SPIRIT_SOURCE || path.resolve(__dirname, '..', '..', 'spirit')
const PY = process.env.SPIRIT_PY || path.resolve(__dirname, '..', '..', '.venv', 'Scripts', 'python.exe')

const home = fs.mkdtempSync(path.join(os.tmpdir(), 'spirit-process-home-'))
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'spirit-process-work-'))

const engine = spawn(PY, ['-m', 'MoBo.main', 'web'], {
  cwd: ROOT,
  env: {
    ...process.env,
    SPIRIT_HOME: home,
    SPIRIT_WORKDIR: work,
    SPIRIT_WEB_PORT: String(PORT),
    SPIRIT_WEB_AUTH: '0',
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
    } catch { /* not yet */ }
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
  const page = await browser.newPage({ viewport: { width: 1200, height: 900 } })
  const errors = []
  page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()) })
  page.on('pageerror', (err) => errors.push(String(err)))

  await page.addInitScript(() => {
    const Original = window.EventSource
    window.__spiritSources = []
    window.EventSource = class extends Original {
      constructor(url, options) {
        super(url, options)
        window.__spiritSources.push(this)
      }
    }
  })
  await page.goto(`http://127.0.0.1:${PORT}/?desktop=1`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1000)
  const emit = (events) => page.evaluate((items) => {
    const source = window.__spiritSources[0]
    for (const item of items) {
      source.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(item) }))
    }
  }, events)

  // 一轮：三段正文 + 两次工具；前两段应进“过程”，最后一段是结论
  await emit([
    { type: 'user_message', text: '播放第三集' },
    { type: 'assistant_message', text: '首页已打开，接下来我会搜索这个节目。' },
    { type: 'tool_call', call_id: 'c1', name: 'browser', arguments: '{"code":"goto v.qq.com"}' },
    { type: 'tool_result', call_id: 'c1', name: 'browser', content: 'ok' },
    { type: 'assistant_message', text: '找到了剧集列表，正在点击第 3 集。' },
    { type: 'tool_call', call_id: 'c2', name: 'browser', arguments: '{"code":"click 3"}' },
    { type: 'tool_result', call_id: 'c2', name: 'browser', content: 'ok' },
    { type: 'assistant_message', text: '第 3 集已经在播放（未暂停、未静音）。' },
    { type: 'assistant_end' },
  ])
  await page.waitForTimeout(400)

  const process = page.locator('.processBlock')
  check(await process.count() === 1, 'one process block')
  check((await process.locator('summary').innerText()).includes('过程 · 2 段'), 'process count 2')
  check(await process.locator('.processBlockBody').isHidden(), 'process collapsed by default')
  check(await process.locator('.processItem').count() === 2, 'two process items')
  const visibleBodies = page.locator('.assistantBody:visible')
  check(await visibleBodies.count() === 1, 'only final answer visible')
  check((await visibleBodies.first().innerText()).includes('第 3 集已经在播放'), 'final answer visible')

  await process.locator('summary').click()
  await page.waitForTimeout(150)
  check(await process.locator('.processBlockBody').isVisible(), 'process opens on click')
  const first = await process.locator('.processItem').first().innerText()
  check(first.includes('首页已打开'), 'process item text')
  const style = await process.locator('.processItem .assistantBody').first().evaluate((el) => getComputedStyle(el).fontSize)
  check(style === '12.5px', `process font ${style}`)

  await process.locator('summary').click()  // 收起上一轮过程，避免干扰可见性断言
  // 新一轮只有一条正文：不生成过程块
  await emit([
    { type: 'user_message', text: '只问一句' },
    { type: 'assistant_message', text: '这是唯一的一段回答。' },
    { type: 'assistant_end' },
  ])
  await page.waitForTimeout(400)
  check(await page.locator('.processBlock').count() === 1, 'single body adds no process block')
  const bodies = page.locator('.assistantBody:visible')
  check(await bodies.count() === 2, 'previous final + single body visible')
  check((await bodies.last().innerText()).includes('唯一的一段回答'), 'single body content')

  // 旧轮的 idle 定时器不能把新一轮标成“已完成”
  await emit([
    { type: 'user_message', text: '旧轮' },
    { type: 'assistant_message', text: '旧轮回答' },
    { type: 'assistant_end' },
  ])
  await page.evaluate(() => window.__spiritStartTurn())
  await page.waitForTimeout(1200)
  const newHead = page.locator('.turnHead').last()
  check(!(await newHead.innerText()).includes('已完成'), 'stale idle must not finish new turn')

  check(errors.length === 0, `console errors ${errors.length} ${errors.slice(0, 2).join(' | ')}`)
  await browser.close()
  engine.kill()
  console.log('\nPROCESS RENDER UI OK')
})().catch((err) => { console.error(err); try { engine.kill() } catch {} ; process.exit(1) })
