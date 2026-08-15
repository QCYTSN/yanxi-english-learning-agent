import { expect, test } from '@playwright/test'
import { mutationHeaders } from './helpers'

test.use({ viewport: { width: 375, height: 812 } })

test('launches the Yanxi learning surfaces on a small screen', async ({ page }) => {
  const baseUrl = process.env.IELTS_E2E_BASE_URL
  test.skip(!baseUrl, 'IELTS_E2E_BASE_URL is required for the packaged-app smoke test')

  await page.goto('/today')
  await expect(page).toHaveURL(/\/today$/)
  await expect(page.getByRole('heading', { name: /今天/ }).first()).toBeVisible()
  await expect(page.getByRole('navigation', { name: '学习导航' })).toBeVisible()
  await expect(page.getByRole('textbox', { name: '向老师提问' })).toBeVisible()
  for (const module of ['听力', '阅读', '写作', '口语']) {
    await expect(page.getByRole('button', { name: module, exact: true })).toBeVisible()
  }
  expect(await hasHorizontalOverflow(page)).toBe(false)

  const threadResponse = await page.request.post('/api/v1/study-threads', {
    headers: await mutationHeaders(page, baseUrl!),
    data: {
      title: '阅读精读测试',
      module: 'reading',
      source_context: {},
    },
  })
  expect(threadResponse.ok()).toBe(true)
  const thread = await threadResponse.json()
  await page.goto(`/study/${thread.thread_id}`)
  await expect(page.getByRole('heading', { name: '阅读精读测试' })).toBeVisible()
  await expect(page.getByRole('main', { name: 'IELTS 学习对话' })).toBeVisible()
  expect(await hasHorizontalOverflow(page)).toBe(false)

  // Two-step speaking flow replaces the old Voice/Live handoff.
  await page.goto('/practice/speaking')
  await expect(page.getByRole('heading', { name: '口语练习' })).toBeVisible()
  await expect(page.getByRole('heading', { name: /第一步/ })).toBeVisible()
  await page.getByRole('button', { name: /我已经拿到任务了，去录音/ }).click()
  await expect(page.getByRole('heading', { name: /第二步/ })).toBeVisible()
  await page.getByRole('button', { name: /我录完了，要贴回转写/ }).click()
  await expect(page.getByRole('heading', { name: '带回来点评' })).toBeVisible()
  expect(await hasHorizontalOverflow(page)).toBe(false)

  await page.goto('/practice/listening')
  await expect(page.getByRole('heading', { name: '高频场景听辨' })).toBeVisible()
  // Public installs start with an empty bank: the friendly empty state shows.
  await expect(page.getByText('本机还没有听力素材')).toBeVisible()
  await expect(page.getByRole('heading', { name: '当前场景表达' })).toBeVisible()
  expect(await hasHorizontalOverflow(page)).toBe(false)
})

function hasHorizontalOverflow(page: import('@playwright/test').Page) {
  return page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
}
