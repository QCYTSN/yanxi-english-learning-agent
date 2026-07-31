import { expect, test } from '@playwright/test'

test.use({ viewport: { width: 375, height: 812 } })

test('keeps the learning shell usable across phone and landscape widths', async ({ page }) => {
  const baseUrl = process.env.IELTS_E2E_BASE_URL
  test.skip(!baseUrl, 'IELTS_E2E_BASE_URL is required for the packaged-app smoke test')

  await page.goto('/today')
  await expect(page.getByRole('heading', { name: /今天/ }).first()).toBeVisible()
  await expect(page.getByRole('navigation', { name: '学习导航' })).toBeVisible()
  expect(await hasHorizontalOverflow(page)).toBe(false)

  await page.goto('/practice?module=reading')
  await expect(page.getByRole('heading', { name: '按科目进入正式学习流程' })).toBeVisible()
  await expect(page.getByText(/\d+ 篇可见内容/)).toBeVisible()
  expect(await hasHorizontalOverflow(page)).toBe(false)

  await page.goto('/library')
  await expect(page.getByRole('heading', { name: '选择材料，直接开始练习' })).toBeVisible()
  await page.getByRole('link', { name: '管理本地材料' }).click()
  await expect(page).toHaveURL(/\/content-studio$/)
  await expect(page.getByRole('heading', { name: '把原始材料整理成可审核的练习内容' })).toBeVisible()
  await page.getByRole('tab', { name: '材料处理' }).click()
  await expect(page.getByText('扫描件与截图文字识别')).toBeVisible()
  await expect(page.getByText('本地材料空间')).toBeVisible()
  await expect(page.getByRole('button', { name: '批量分析 PDF' })).toBeVisible()
  await page.getByRole('link', { name: '返回学习资料库' }).click()
  await expect(page).toHaveURL(/\/library$/)
  expect(await hasHorizontalOverflow(page)).toBe(false)

  await page.goto('/content-studio?import=promoted-material')
  await expect(page.getByRole('tab', { name: '材料处理' })).toHaveAttribute('aria-selected', 'true')

  await page.setViewportSize({ width: 844, height: 390 })
  await page.goto('/today')
  await expect(page.getByRole('heading', { name: /今天/ }).first()).toBeVisible()
  expect(await hasHorizontalOverflow(page)).toBe(false)
  const threadResponse = await page.request.post('/api/v1/study-threads', {
    headers: { Origin: baseUrl! },
    data: {
      title: 'Sidebar layout check',
      module: 'reading',
      source_context: {},
    },
  })
  expect(threadResponse.ok()).toBe(true)
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto('/today')
  const finalNavItem = await page.locator('.primary-nav .nav-link').last().boundingBox()
  const recentThreads = await page.locator('.recent-study-threads').boundingBox()
  expect(finalNavItem).not.toBeNull()
  expect(recentThreads).not.toBeNull()
  expect(recentThreads!.y).toBeGreaterThanOrEqual(finalNavItem!.y + finalNavItem!.height)
})

function hasHorizontalOverflow(page: import('@playwright/test').Page) {
  return page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
}
