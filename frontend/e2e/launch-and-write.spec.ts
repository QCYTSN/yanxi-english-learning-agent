import { expect, test } from '@playwright/test'

test.use({ viewport: { width: 375, height: 812 } })

test('launches the packaged four-module study desk on a small screen', async ({ page }) => {
  const baseUrl = process.env.IELTS_E2E_BASE_URL
  test.skip(!baseUrl, 'IELTS_E2E_BASE_URL is required for the packaged-app smoke test')

  await page.goto('/today')
  await expect(page).toHaveURL(/\/today$/)
  await expect(page.getByRole('heading', { name: /今天/ }).first()).toBeVisible()
  await expect(page.getByRole('navigation', { name: '学习导航' })).toBeVisible()
  await expect(page.getByPlaceholder('上传题目、原文或作文，然后告诉我你想弄懂什么…')).toBeVisible()
  for (const module of ['听力', '阅读', '写作', '口语']) {
    await expect(page.getByRole('button', { name: module, exact: true })).toBeVisible()
  }
  expect(await hasHorizontalOverflow(page)).toBe(false)

  const threadResponse = await page.request.post('/api/v1/study-threads', {
    headers: { Origin: baseUrl! },
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

  await page.goto('/today')
  await page.getByRole('button', { name: '口语', exact: true }).click()
  await page.getByRole('button', { name: '进入工作区' }).click()
  await expect(page.getByRole('heading', { name: '把口语流程交给 Voice / Live 主持' })).toBeVisible()
  await expect(page.getByText('计时属于外部主持方')).toBeVisible()
  await page.getByRole('button', { name: '生成任务包' }).click()
  await expect(page.getByRole('textbox', { name: 'Speaking Voice Live 任务包' })).toBeVisible()
  expect(await hasHorizontalOverflow(page)).toBe(false)

  await page.goto('/practice/listening')
  await expect(page.getByRole('heading', { name: '高频场景听辨' })).toBeVisible()
  await page.getByRole('button', { name: '开始训练' }).click()
  await expect(page.getByRole('button', { name: /播放英式系统语音/ })).toBeVisible()
  await expect(page.getByRole('textbox', { name: '你的答案' })).toBeVisible()
  expect(await hasHorizontalOverflow(page)).toBe(false)
})

function hasHorizontalOverflow(page: import('@playwright/test').Page) {
  return page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)
}
