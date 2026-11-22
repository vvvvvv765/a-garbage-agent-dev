// 冒烟：设置 → 通用 → 「不可信内容之后」三档可切换
const { chromium } = require('playwright')

;(async () => {
  const browser = await chromium.launch({ channel: 'msedge' })
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  await page.goto('http://127.0.0.1:5083/?desktop=1', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(800)

  await page.click('#accountBtn')
  await page.waitForTimeout(400)
  await page.locator('#untrustedSeg').scrollIntoViewIfNeeded()
  await page.waitForTimeout(200)
  await page.screenshot({ path: 'tupian/spirit_untrusted_setting.png' })

  await page.click('#untrustedSeg button[data-value="warn"]')
  await page.waitForTimeout(500)
  const policy = await page.evaluate(() =>
    fetch('/api/settings').then((res) => res.json()).then((data) => data.untrusted_policy)
  )
  console.log('policy after click:', policy)

  await page.click('#untrustedSeg button[data-value="confirm"]')
  await page.waitForTimeout(400)
  const back = await page.evaluate(() =>
    fetch('/api/settings').then((res) => res.json()).then((data) => data.untrusted_policy)
  )
  console.log('policy restored:', back)

  await browser.close()
})().catch((error) => {
  console.error(error)
  process.exit(1)
})
