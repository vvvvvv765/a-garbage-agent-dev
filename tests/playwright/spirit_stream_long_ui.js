/* 长回复流式：稳定段只渲染一次，代码块不被空行拆开，最终内容完整 */
const { chromium } = require('playwright')
const { spawn } = require('node:child_process')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const PORT = 5123
const ROOT = process.env.SPIRIT_SOURCE || path.resolve(__dirname, '..', '..', 'spirit')
const PY = process.env.SPIRIT_PY || path.resolve(__dirname, '..', '..', '.venv', 'Scripts', 'python.exe')

const home = fs.mkdtempSync(path.join(os.tmpdir(), 'spirit-long-home-'))
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'spirit-long-work-'))

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
  const page = await browser.newPage({ viewport: { width: 1400, height: 900 } })
  const errors = []
  page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()) })
  page.on('pageerror', (err) => errors.push(String(err)))

  await page.addInitScript(() => {
    window.__spiritMarkdownStats = { calls: 0, chars: 0 }
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
  await page.waitForTimeout(900)
  const emit = (events) => page.evaluate((items) => {
    const source = window.__spiritSources[0]
    for (const item of items) {
      source.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(item) }))
    }
  }, events)

  const chunks = []
  for (let i = 0; i < 60; i += 1) {
    chunks.push(`第 ${i} 段：` + '内容填充'.repeat(24) + '\n\n')
    if (i === 20) chunks.push('```js\nconst a = 1\n\nconst b = 2\n```\n\n')
  }
  const full = chunks.join('')

  await emit([{ type: 'user_message', text: '写一段长回复' }])
  for (const chunk of chunks) {
    await emit([{ type: 'assistant_delta', text: chunk }])
    await page.waitForTimeout(25)
  }
  await emit([
    { type: 'assistant_final', text: full },
    { type: 'assistant_end' },
  ])
  await page.waitForTimeout(400)

  const md = page.locator('.markdownBody').last()
  const text = await md.innerText()
  check(text.includes('第 0 段'), 'first paragraph present')
  check(text.includes('第 59 段'), 'last paragraph present')
  check((text.match(/第 0 段/g) || []).length === 1, 'no duplicated paragraph')
  const pres = md.locator('pre')
  check(await pres.count() === 1, 'one code block')
  const code = await pres.first().innerText()
  check(code.includes('const a = 1') && code.includes('const b = 2'), 'code block intact across blank line')

  const stats = await page.evaluate(() => window.__spiritMarkdownStats)
  console.log('markdown parsed:', stats.calls, 'calls /', stats.chars, 'chars (full', full.length, ')')
  check(stats.chars < full.length * 3, `incremental parse total ${stats.chars} < full*3 ${full.length * 3}`)
  check(errors.length === 0, `console errors ${errors.slice(0, 2).join(' | ')}`)

  await browser.close()
  console.log('\nLONG STREAM UI OK')
})().catch((err) => {
  console.error(err)
  process.exitCode = 1
}).finally(async () => {
  try { engine.kill() } catch { /* ignore */ }
  await new Promise((r) => setTimeout(r, 300))
  process.exit(process.exitCode || 0)
})
