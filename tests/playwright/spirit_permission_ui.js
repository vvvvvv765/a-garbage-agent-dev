/* 权限两轴界面：范围（可修改/查看）+ 模式（询问/⏵⏵自动）+ Shift+Tab 循环 */
const { chromium } = require('playwright')
const { spawn } = require('node:child_process')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')

const PORT = 5095
const ROOT = process.env.SPIRIT_SOURCE || path.resolve(__dirname, '..', '..', 'spirit')
const PY = process.env.SPIRIT_PY || path.resolve(__dirname, '..', '..', '.venv', 'Scripts', 'python.exe')
const SHOTS = path.join(os.tmpdir(), 'spirit-tupian')

const home = fs.mkdtempSync(path.join(os.tmpdir(), 'spirit-perm-ui-home-'))
const work = fs.mkdtempSync(path.join(os.tmpdir(), 'spirit-perm-ui-work-'))

const engine = spawn(PY, ['-m', 'MoBo.main', 'web'], {
  cwd: ROOT,
  env: {
    ...process.env,
    SPIRIT_HOME: home,
    SPIRIT_WORKDIR: work,
    SPIRIT_WEB_PORT: String(PORT),
    SPIRIT_WEB_AUTH: '0', // 测试：关掉控制面令牌（鉴权由 spirit_web_auth_test 覆盖）
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

async function settings() {
  return fetch(`http://127.0.0.1:${PORT}/api/settings`).then((r) => r.json())
}

;(async () => {
  await waitReady()
  const browser = await chromium.launch({ channel: 'msedge' })
  const page = await browser.newPage({ viewport: { width: 1500, height: 950 } })
  const errors = []
  page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()) })
  page.on('pageerror', (err) => errors.push(String(err)))

  // 留住 EventSource，后面手工灌一条审批事件验卡片（不真发请求）
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
  await page.waitForTimeout(1200)

  // 两个 chip 各管一轴
  check((await page.locator('#accessLabel').innerText()) === '可修改', 'access label default')
  check((await page.locator('#approvalLabel').innerText()) === '询问', 'approval label default')
  check(await page.locator('#autoHint').isHidden(), 'auto hint hidden by default')

  // 模式：询问 → 自动
  await page.click('#workdirChip')
  await page.waitForTimeout(150)
  const modes = await page.locator('#approvalPop button[data-mode]').allInnerTexts()
  check(modes.length === 2 && modes[0].includes('询问') && modes[1].includes('自动'), `mode options ${modes}`)
  await page.locator('#approvalPop button[data-mode="auto"]').click()
  await page.waitForTimeout(400)
  check((await page.locator('#approvalLabel').innerText()).includes('自动'), 'approval chip auto')
  check(await page.locator('#autoHint').isVisible(), 'auto hint visible')
  let res = await settings()
  check(res.approval === 'auto', `settings approval ${res.approval}`)

  // Shift+Tab 循环回询问
  await page.focus('#input')
  await page.keyboard.press('Shift+Tab')
  await page.waitForTimeout(400)
  check((await page.locator('#approvalLabel').innerText()) === '询问', 'shift+tab cycles to ask')
  check(await page.locator('#autoHint').isHidden(), 'auto hint hidden after cycle')
  res = await settings()
  check(res.approval === 'ask', `settings approval ${res.approval}`)

  // 范围：可修改 → 查看
  await page.click('#accessChip')
  await page.waitForTimeout(150)
  const accessOptions = await page.locator('#accessPop button[data-access]').allInnerTexts()
  check(accessOptions.length === 2 && accessOptions[1].includes('查看'), `access options ${accessOptions}`)
  await page.locator('#accessPop button[data-access="readonly"]').click()
  await page.waitForTimeout(400)
  check((await page.locator('#accessLabel').innerText()) === '查看', 'access chip readonly')
  res = await settings()
  check(res.access === 'readonly', `settings access ${res.access}`)
  await page.screenshot({ path: path.join(SHOTS, 'spirit_permission_axes.png') })

  // 旧的全局沙箱 / 可访问路径设置已移除；沙箱改为 sandbox_run 能力
  await page.click('#menuBtn')
  await page.click('#menuPop button[data-action="general-settings"]')
  await page.waitForTimeout(300)
  check(await page.locator('#sandboxSwitch').count() === 0, 'sandbox switch removed')
  check(await page.locator('#sandboxPathList').count() === 0, 'sandbox paths removed')
  check(await page.locator('#outsideSwitch').count() === 0, 'outside switch removed')
  check((await page.locator('.settings-panel[data-panel="general"]').innerText()).includes('不可信内容之后'),
    'settings still healthy')
  await page.click('#closeSettings')
  await page.waitForTimeout(200)
  await page.click('#accessChip')
  await page.waitForTimeout(100)
  check(await page.locator('#accessPop button[data-outside-auto]').count() === 1,
    'outside access control in range menu')
  check((await page.locator('#outsideAutoState').innerText()) === '自动允许',
    'outside access auto allowed')
  await page.keyboard.press('Escape')
  await page.waitForTimeout(100)

  // 审批卡：工作区外访问请求的专用文案
  await page.evaluate(() => {
    const source = window.__spiritSources[0]
    source.dispatchEvent(new MessageEvent('message', {
      data: JSON.stringify({
        type: 'approval_request',
        id: 'fake-access-1',
        name: 'read_file',
        kind: 'access',
        path: 'D:\\outside\\secret.txt',
        reason: 'D:\\outside\\secret.txt 不在工作区内',
        mode: 'ask',
        access: 'workspace',
      }),
    }))
  })
  await page.waitForTimeout(300)
  const card = page.locator('.approvalCard').last()
  check((await card.locator('.approvalTitle').innerText()) === '需要访问工作区外的路径', 'access card title')
  check((await card.locator('.approvalTool').innerText()).includes('outside'), 'access card path')
  check((await card.locator('.approvalArgs').innerText()).includes('不在工作区'), 'access card reason')
  check((await card.locator('.approvalHint').innerText()).includes('可访问的路径'), 'access card hint')
  check((await card.locator('button.approve').innerText()) === '允许本次', 'access card allow label')
  check((await card.locator('button.ghost').innerText()) === '本次运行都允许', 'access card remember label')

  // 两个 pop 互斥
  await page.click('#workdirChip')
  await page.waitForTimeout(100)
  check(await page.locator('#approvalPop').isVisible(), 'approval pop open')
  await page.click('#accessChip')
  await page.waitForTimeout(100)
  check(await page.locator('#approvalPop').isHidden() && await page.locator('#accessPop').isVisible(), 'pops exclusive')

  check(errors.length === 0, `console errors ${errors.length} ${errors.slice(0, 2).join(' | ')}`)

  await browser.close()
  console.log('\nPERMISSION AXES UI OK')
})().catch(async (err) => {
  console.error(err)
  process.exitCode = 1
}).finally(async () => {
  try { engine.kill() } catch { /* ignore */ }
  await new Promise((r) => setTimeout(r, 300))
  process.exit(process.exitCode || 0)
})
