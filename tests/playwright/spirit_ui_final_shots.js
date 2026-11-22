// 最终 UI 截图：渗透模式主界面 + 信息收集弹窗
const { chromium } = require('playwright')

;(async () => {
  const browser = await chromium.launch({ channel: 'msedge' })
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 } })
  await page.goto('http://127.0.0.1:5091/', { waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1200)
  await page.evaluate(async () => {
    const token = document.querySelector('meta[name="spirit-api-token"]')?.content || ''
    await fetch('/api/scenario', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Spirit-Token': token },
      body: JSON.stringify({ id: 'pentest' }),
    })
  })
  await page.reload({ waitUntil: 'domcontentloaded' })
  await page.waitForTimeout(1500)
  const info = await page.evaluate(() => ({
    bodyScenario: document.body.dataset.scenario,
    tabMoreHTML: document.getElementById('tabMore')?.innerHTML.trim().slice(0, 60),
    approval: document.getElementById('approvalLabel')?.textContent,
  }))
  console.log(JSON.stringify(info))
  await page.screenshot({ path: 'tupian/spirit_ui_main.png' })

  await page.click('#tabMore')
  await page.waitForTimeout(300)
  await page.click('#infoButton')
  await page.waitForTimeout(900)
  await page.evaluate(() => document.querySelector('.collect-section')?.scrollIntoView({ block: 'start' }))
  await page.waitForTimeout(300)
  await page.screenshot({ path: 'tupian/spirit_ui_collect.png' })
  await browser.close()
  console.log('SHOTS OK')
})()
