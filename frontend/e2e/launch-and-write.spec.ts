import { expect, test } from '@playwright/test'

test.use({ viewport: { width: 375, height: 812 } })

test('launches the packaged four-module study desk on a small screen', async ({ page }) => {
  const launchUrl = process.env.IELTS_E2E_LAUNCH_URL
  test.skip(!launchUrl, 'IELTS_E2E_LAUNCH_URL is required for the packaged-app smoke test')

  await page.goto(launchUrl!)
  await expect(page).toHaveURL(/\/today$/)
  await expect(page.getByRole('heading', { name: '今天只推进一件重要的事' })).toBeVisible()
  await expect(page.getByRole('navigation', { name: '主要导航' })).toBeVisible()
  for (const module of ['Writing', 'Reading', 'Speaking', 'Listening']) {
    await expect(page.getByRole('heading', { name: module, exact: true })).toBeVisible()
  }
  expect(await hasHorizontalOverflow(page)).toBe(false)

  await page.getByRole('link', { name: /Speaking/ }).click()
  await page.getByRole('button', { name: '进入工作区' }).click()
  await expect(page.getByRole('heading', { name: '把口语流程交给 Voice / Live 主持' })).toBeVisible()
  await expect(page.getByText('计时属于外部主持方')).toBeVisible()
  await page.getByRole('button', { name: '生成任务包' }).click()
  await expect(page.getByRole('textbox', { name: 'Speaking Voice Live 任务包' })).toBeVisible()
  expect(await hasHorizontalOverflow(page)).toBe(false)

  await page.goto(new URL('/practice/listening', page.url()).toString())
  await expect(page.getByRole('heading', { name: '高频场景听辨' })).toBeVisible()
  await page.getByRole('button', { name: '开始训练' }).click()
  await expect(page.getByRole('button', { name: /播放英式系统语音/ })).toBeVisible()
  await expect(page.getByRole('textbox', { name: '你的答案' })).toBeVisible()
  expect(await hasHorizontalOverflow(page)).toBe(false)
})

function hasHorizontalOverflow(page: import('@playwright/test').Page) {
  return page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
}
