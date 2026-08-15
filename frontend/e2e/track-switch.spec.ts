import { expect, test } from '@playwright/test'
import { mutationHeaders } from './helpers'

test('switches learning mode from Settings and keeps both tracks registered', async ({ page }) => {
  const baseUrl = process.env.IELTS_E2E_BASE_URL
  test.skip(!baseUrl, 'IELTS_E2E_BASE_URL is required')

  await page.goto('/settings/profile')
  await expect(page.getByRole('heading', { name: '学习模式' })).toBeVisible()

  // Fresh homes default to General English.
  const general = page.locator('.track-choice', { hasText: '通用英语' })
  const ielts = page.locator('.track-choice', { hasText: 'IELTS Academic' })
  await expect(general).toHaveClass(/selected/)

  await ielts.click()
  await expect(ielts).toHaveClass(/selected/)

  const switched = await page.request.get('/api/v1/bootstrap')
  const payload = await switched.json()
  expect(payload.active_learning_track_id).toBe('ielts-academic')

  // Switching back restores the general track without losing the registered pack.
  await general.click()
  await expect(general).toHaveClass(/selected/)
  const restored = await (await page.request.get('/api/v1/bootstrap')).json()
  expect(restored.active_learning_track_id).toBe('general-english')
  expect(restored.learning_tracks.map((item: { track_id: string }) => item.track_id)).toEqual(
    expect.arrayContaining(['general-english', 'ielts-academic']),
  )
})

test('rejects an invalid track id through the profile API', async ({ page }) => {
  const baseUrl = process.env.IELTS_E2E_BASE_URL
  test.skip(!baseUrl, 'IELTS_E2E_BASE_URL is required')

  const response = await page.request.put('/api/v1/profile', {
    headers: await mutationHeaders(page, baseUrl!),
    data: { updates: { active_learning_track_id: 'not-a-track' } },
  })
  expect(response.status()).toBe(422)
})
