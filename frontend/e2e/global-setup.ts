import { chromium } from '@playwright/test'
import { mkdir } from 'node:fs/promises'
import { dirname, resolve } from 'node:path'

const authStatePath = resolve('e2e/.auth/state.json')

export default async function globalSetup() {
  const launchUrl = process.env.IELTS_E2E_LAUNCH_URL
  if (!launchUrl) return
  await mkdir(dirname(authStatePath), { recursive: true })
  const browser = await chromium.launch()
  const context = await browser.newContext()
  const page = await context.newPage()
  await page.goto(launchUrl)
  await page.waitForURL(/\/today$/)
  await context.storageState({ path: authStatePath })
  await browser.close()
}
