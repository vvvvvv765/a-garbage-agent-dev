/* 工具行渲染：call_id 匹配、结果预览、折叠/展开、失败自动展开、异常可折叠 */
const { chromium } = require('playwright')
const { spawn } = require('node:child_process')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const PORT = 5099
const ROOT = process.env.SPIRIT_SOURCE || path.resolve(__dirname, '..', '..', 'spirit')
const PY = process.env.SPIRIT_PY || path.resolve(__dirname, '..', '..', '.venv', 'Scripts', 'python.exe')

const home = fs.mkdtempSync(path.join(os.tmpdir(), 'spirit-render-home-'))
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'spirit-render-work-'))

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
  const page = await browser.newPage({ viewport: { width: 1200, height: 800 } })
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

  // 两个工具，结果乱序返回：必须按 call_id 对上
  await emit([
    { type: 'user_message', text: '看一下项目' },
    { type: 'tool_call', call_id: 'c1', name: 'list_dir', arguments: '{"path":"Engine"}' },
    { type: 'tool_call', call_id: 'c2', name: 'read_file', arguments: '{"path":"a.py"}' },
    { type: 'tool_result', call_id: 'c2', name: 'read_file', content: 'print(1)\nprint(2)' },
    { type: 'tool_result', call_id: 'c1', name: 'list_dir', content: 'core.py\nfaults.py' },
  ])
  await page.waitForTimeout(300)
  const rows = page.locator('.toolRow')
  const group = page.locator('.toolGroup').first()
  check(await rows.count() === 2, 'two tool rows')
  check(await group.count() === 1, 'tool group present')
  check((await group.locator('.toolGroupMeta').innerText()).trim() === '2 个', 'group count 2')
  check((await group.locator('.toolGroupState').innerText()).trim() === '已返回', 'group state returned')
  check(await group.locator('.toolGroupBody').isHidden(), 'group collapsed by default')
  await emit([{ type: 'assistant_end' }])
  await page.waitForTimeout(1200)   // 轮次收尾有 0.8s 空闲延迟
  check(await group.locator('.toolGroupBody').isHidden(), 'group stays collapsed at turn end')

  // 失败结果自动展开外层
  await emit([
    { type: 'tool_call', call_id: 'c3', name: 'bash', arguments: '{"command":"rm -rf C:\\\\"}' },
    { type: 'tool_result', call_id: 'c3', name: 'bash', content: '沙箱拒绝：灾难闸拒绝：C:\\ 是磁盘根目录' },
  ])
  await page.waitForTimeout(300)
  const failed = rows.nth(2)
  check((await group.locator('.toolGroupMeta').innerText()).trim() === '3 个', 'group count 3')
  check((await group.locator('.toolGroupState').innerText()).includes('失败'), 'group reports failure')
  check(await group.locator('.toolGroupBody').isHidden(), 'group stays collapsed on failure')
  await group.locator('.toolGroupHead').click()
  await page.waitForTimeout(150)
  check((await rows.nth(0).locator('.toolTitle').innerText()) === 'list_dir', 'row1 title')
  check((await rows.nth(1).locator('.toolTitle').innerText()) === 'read_file', 'row2 title')
  check(await rows.nth(0).locator('.toolBody').isHidden(), 'body collapsed by default')
  check(await rows.nth(0).locator('.toolPreview').isHidden(), 'preview hidden while collapsed')
  await rows.nth(0).locator('.toolHead').click()
  await page.waitForTimeout(150)
  check(await rows.nth(0).locator('.toolBody').isVisible(), 'body expands on click')
  check((await rows.nth(0).locator('.toolPreview').innerText()).includes('core.py'), 'row1 result matched by call_id')
  check((await rows.nth(0).locator('.toolBody .toolPre').nth(1).innerText()).includes('faults.py'), 'full output in body')
  await rows.nth(1).locator('.toolHead').click()
  await page.waitForTimeout(150)
  check((await rows.nth(1).locator('.toolPreview').innerText()).includes('print(1)'), 'row2 result matched by call_id')
  check((await failed.getAttribute('class')).includes('failed'), 'failed row marked')
  check((await failed.locator('.toolState').innerText()) === '失败', 'failed state text')
  check(await failed.locator('.toolBody').isHidden(), 'failed row stays collapsed')

  // 异常折叠
  await emit([{
    type: 'exception', system: 'CPU', where: 'max_steps', kind: 'Error',
    message: '工具跟进超过 8 步，停止本轮',
  }])
  await page.waitForTimeout(300)
  const err = page.locator('.errorDetails').last()
  check(await err.isVisible(), 'error details visible')
  check((await err.locator('summary').innerText()).includes('工具步数达到上限'), 'max_steps friendly label')
  check(await err.locator('.errorRow').isHidden(), 'error body collapsed')
  await err.locator('summary').click()
  await page.waitForTimeout(150)
  check(await err.locator('.errorRow').isVisible(), 'error body expands')

  check(errors.length === 0, `console errors ${errors.length} ${errors.slice(0, 2).join(' | ')}`)
  await browser.close()
  console.log('\nTOOL RENDER UI OK')
})().catch((err) => {
  console.error(err)
  process.exitCode = 1
}).finally(async () => {
  try { engine.kill() } catch { /* ignore */ }
  await new Promise((r) => setTimeout(r, 300))
  process.exit(process.exitCode || 0)
})
