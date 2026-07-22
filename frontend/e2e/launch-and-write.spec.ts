import { expect, test } from '@playwright/test'

test.use({ viewport: { width: 375, height: 812 } })

test('exchanges the launch token and opens a writing workspace on a small screen', async ({ page }) => {
  const launchUrl = process.env.IELTS_E2E_LAUNCH_URL
  test.skip(!launchUrl, 'IELTS_E2E_LAUNCH_URL is required for the packaged-app smoke test')

  await page.goto(launchUrl!)
  await expect(page).toHaveURL(/\/today$/)
  await expect(page.getByRole('heading', { name: '今天只推进一件重要的事' })).toBeVisible()
  await expect(page.getByRole('navigation', { name: '主要导航' })).toBeVisible()
  expect(await hasHorizontalOverflow(page)).toBe(false)

  await page.getByRole('link', { name: '开始练习', exact: true }).click()
  await expect(page.getByRole('heading', { name: '选择练习' })).toBeVisible()
  await page.getByRole('button', { name: '开始练习', exact: true }).first().click()
  await expect(page.getByRole('heading', { name: 'Writing 工作区' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: '作文内容' })).toBeVisible()
  expect(await hasHorizontalOverflow(page)).toBe(false)
})

function hasHorizontalOverflow(page: import('@playwright/test').Page) {
  return page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
}
