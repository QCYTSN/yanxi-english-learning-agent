import type { Page } from '@playwright/test'

export async function mutationHeaders(page: Page, baseUrl: string) {
  const cookies = await page.context().cookies(baseUrl)
  const csrf = cookies.find((cookie) => cookie.name === 'ielts_ui_csrf')
  if (!csrf?.value) {
    throw new Error('Authenticated UI session did not expose its CSRF token')
  }
  return {
    Origin: baseUrl,
    'X-IELTS-CSRF': csrf.value,
  }
}
