// 冒烟：渗透场景下标题栏出现「授权范围」，弹窗可编辑
const { chromium } = require('playwright')

;(async () => {
  const browser = await chromium.launch({ channel: 'msedge' })
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } })
  await page.goto('http://127.0.0.1:5081/?desktop=1', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(600)

  await page.evaluate(async () => {
    await fetch('/api/scenario', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: 'pentest' }),
    })
  })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(800)

  const titlebar = await page.locator('#titlebar').isVisible()
  const scopeVisible = await page.locator('#scopeBtn').isVisible()
  console.log('titlebar:', titlebar, 'scope btn:', scopeVisible)
  await page.screenshot({ path: 'tupian/spirit_scope_bar.png' })

  await page.click('#scopeBtn')
  await page.fill('#scopeInput', 'example.com\n10.0.0.5')
  await page.waitForTimeout(200)
  await page.screenshot({ path: 'tupian/spirit_scope_modal.png' })

  await page.click('#scopeSave')
  await page.waitForTimeout(500)
  const count = await page.locator('#scopeCount').textContent()
  console.log('count:', count)

  await page.evaluate(async () => {
    await fetch('/api/scenario', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id: 'daily' }),
    })
  })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(600)
  console.log('daily scope hidden:', !(await page.locator('#scopeBtn').isVisible()))

  await browser.close()
})().catch((error) => {
  console.error(error)
  process.exit(1)
})
