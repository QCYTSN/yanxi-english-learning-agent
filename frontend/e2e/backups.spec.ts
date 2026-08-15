import { expect, test } from '@playwright/test'

test('creates a manual backup from the local data settings', async ({ page }) => {
  const baseUrl = process.env.IELTS_E2E_BASE_URL
  test.skip(!baseUrl, 'IELTS_E2E_BASE_URL is required')

  const before = await (await page.request.get('/api/v1/backups')).json()
  const beforeCount = before.length

  await page.goto('/settings/data')
  await expect(page.getByRole('heading', { name: '备份与恢复' })).toBeVisible()
  await page.getByRole('button', { name: /创建备份/ }).click()

  // Poll until the new manual-ui backup shows up in the list.
  await expect(async () => {
    const backups = await (await page.request.get('/api/v1/backups')).json()
    expect(backups.length).toBeGreaterThan(beforeCount)
  }).toPass({ timeout: 20_000 })
})
