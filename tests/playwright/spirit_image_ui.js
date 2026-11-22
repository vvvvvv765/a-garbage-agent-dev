/* 图片输入：选图 → 上传预览 → 发送进对话 → 历史回放 */
const { chromium } = require('playwright')
const { spawn } = require('node:child_process')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const PORT = 5107
const ROOT = process.env.SPIRIT_SOURCE || path.resolve(__dirname, '..', '..', 'spirit')
const PY = process.env.SPIRIT_PY || path.resolve(__dirname, '..', '..', '.venv', 'Scripts', 'python.exe')

const home = fs.mkdtempSync(path.join(os.tmpdir(), 'spirit-image-home-'))
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'spirit-image-work-'))

// 1x1 PNG
const PNG = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Y9Z1ZkAAAAASUVORK5CYII=',
  'base64',
)
const imagePath = path.join(home, 'pixel.png')
fs.writeFileSync(imagePath, PNG)

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
  const page = await browser.newPage({ viewport: { width: 1500, height: 950 } })
  const errors = []
  page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()) })
  page.on('pageerror', (err) => errors.push(String(err)))

  // 拦发送：不让测试真的叫模型
  let sentBody = null
  await page.route('**/api/send', async (route) => {
    sentBody = route.request().postDataJSON()
    await route.fulfill({ status: 200, contentType: 'application/json', body: '{"ok":true}' })
  })

  await page.goto(`http://127.0.0.1:${PORT}/?desktop=1`, { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1000)
  await page.evaluate(() => document.querySelector('.shell').classList.remove('hero'))

  // 初始：预览区隐藏、发送按钮禁用
  check(await page.locator('#attachPreview').isHidden(), 'preview hidden initially')
  check(await page.locator('#send').isDisabled(), 'send disabled initially')

  // 选图 → 自动上传 → 出现缩略图
  await page.setInputFiles('#imageFile', imagePath)
  await page.waitForSelector('#attachPreview .attachThumb img', { timeout: 5000 })
  check(!(await page.locator('#attachPreview').isHidden()), 'preview visible after attach')
  check((await page.locator('#attachPreview .attachThumb').count()) === 1, 'one thumbnail')
  check(!(await page.locator('#send').isDisabled()), 'send enabled with image only')

  // 只有图片也能发
  await page.click('#send')
  await page.waitForSelector('.userImages img', { timeout: 5000 })
  check((await page.locator('.userImages img').count()) === 1, 'user bubble image')
  check(sentBody && Array.isArray(sentBody.images) && sentBody.images.length === 1, `send payload ${JSON.stringify(sentBody)}`)
  check(String(sentBody.images[0]).endsWith('.png'), 'payload image id')
  check(await page.locator('#attachPreview').isHidden(), 'preview cleared after send')

  // 图片真的能取回
  const url = await page.locator('.userImages img').first().getAttribute('src')
  check(url.startsWith('data:image/png'), 'bubble src is data url')
  const fetched = await fetch(`http://127.0.0.1:${PORT}/api/upload/${sentBody.images[0]}`)
  check(fetched.status === 200, 'uploaded image served')
  check((await fetched.arrayBuffer()).byteLength === PNG.length, 'uploaded image bytes')

  // 历史里也带回图片（上面拦了发送，这里直连服务端走真实队列）
  await fetch(`http://127.0.0.1:${PORT}/api/send`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: '', images: [sentBody.images[0]] }),
  })
  let userEvent = null
  for (let i = 0; i < 20; i += 1) {
    const data = await fetch(`http://127.0.0.1:${PORT}/api/history`).then((r) => r.json())
    const history = Array.isArray(data) ? data : (data.events || [])
    userEvent = history.filter((ev) => ev.type === 'user_message').pop()
    if (userEvent) break
    await page.waitForTimeout(300)
  }
  check(userEvent && userEvent.images && userEvent.images.length === 1, `history images ${JSON.stringify(userEvent)}`)

  // 移除按钮
  await page.setInputFiles('#imageFile', imagePath)
  await page.waitForSelector('#attachPreview .attachThumb', { timeout: 5000 })
  await page.click('#attachPreview .attachThumb button')
  check(await page.locator('#attachPreview').isHidden(), 'preview hidden after remove')

  check(errors.length === 0, `console errors ${errors.length} ${errors.slice(0, 2).join(' | ')}`)
  await browser.close()
  console.log('\nIMAGE UI OK')
})().catch((err) => {
  console.error(err)
  process.exitCode = 1
}).finally(async () => {
  try { engine.kill() } catch { /* ignore */ }
  await new Promise((r) => setTimeout(r, 300))
  process.exit(process.exitCode || 0)
})
