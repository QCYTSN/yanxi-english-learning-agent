import { expect, test } from '@playwright/test'
import { mutationHeaders } from './helpers'

test('vocabulary word card, adaptive review and typing surface', async ({ page }) => {
  const baseUrl = process.env.IELTS_E2E_BASE_URL
  test.skip(!baseUrl, 'IELTS_E2E_BASE_URL is required')
  const headers = await mutationHeaders(page, baseUrl!)

  const created = await page.request.post('/api/v1/vocabulary', {
    headers,
    data: { word: 'study', meaning: '学习', track_id: 'general-english' },
  })
  expect(created.status()).toBe(200)
  const item = await created.json()

  // Bundled high-frequency preset renders an offline word card.
  const enrichment = await (await page.request.get(`/api/v1/vocabulary/${item.item_id}/enrichment`)).json()
  expect(enrichment.word).toBe('study')
  expect(enrichment.definitions.length).toBeGreaterThan(0)
  expect(enrichment.forms.third_person).toBe('studies')

  // No model in the e2e home: deterministic-only enrichment path.
  const enrich = await page.request.post(`/api/v1/vocabulary/${item.item_id}/enrich`, { headers })
  expect(enrich.status()).toBe(200)
  expect((await enrich.json()).status).toBe('deterministic_only')

  // Adaptive review ladder starts at one day.
  const reviewed = await page.request.patch(`/api/v1/vocabulary/${item.item_id}/review`, {
    headers,
    data: { outcome: 'recalled' },
  })
  expect(reviewed.status()).toBe(200)
  const reviewPayload = await reviewed.json()
  expect(reviewPayload.success_streak).toBe(1)
  expect(reviewPayload.review_interval_days).toBe(1)

  // The typing surface runs a session over the learner's word plus the starter list.
  await page.goto('/practice/typing')
  await expect(page.getByRole('heading', { name: '把词打出来' })).toBeVisible()
  await page.getByRole('button', { name: /开始打词/ }).click()
  await expect(page.locator('.typing-stage')).toBeVisible()
})
