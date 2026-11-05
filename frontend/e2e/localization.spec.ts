import { expect, test } from '@playwright/test'

test.use({ locale: 'de-DE' })

test.beforeEach(async ({ page }) => {
  await page.route(url => url.pathname.startsWith('/api/'), async route => {
    const path = new URL(route.request().url()).pathname
    if (path.endsWith('/auth/status')) {
      await route.fulfill({ json: { success: true, require_login: false, media_server_type: 'emby' } })
    } else if (path.endsWith('/static-session')) {
      await route.fulfill({ json: { party_id: null } })
    } else {
      await route.fulfill({ json: { parties: [] } })
    }
  })
})

test('detects German and persists an English override across reloads', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('button', { name: 'Party erstellen', exact: true })).toBeVisible()
  await expect(page.locator('html')).toHaveAttribute('lang', 'de')
  await page.getByRole('combobox', { name: 'Sprache', exact: true }).selectOption('en')
  await expect(page.getByRole('button', { name: 'Create Party', exact: true })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('button', { name: 'Create Party', exact: true })).toBeVisible()
  await expect(page.locator('html')).toHaveAttribute('lang', 'en')
  await page.getByRole('combobox', { name: 'Language', exact: true }).selectOption('auto')
  await expect(page.getByRole('button', { name: 'Party erstellen', exact: true })).toBeVisible()
})

test('keeps German controls usable on a narrow screen', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto('/')
  await page.getByRole('button', { name: 'Beitreten', exact: true }).click()
  await expect(page.getByText('Bitte gib einen gültigen Party-Code ein')).toBeVisible()
  await page.getByRole('combobox', { name: 'Sprache', exact: true }).selectOption('en')
  await expect(page.getByText('Please enter a valid party code')).toBeVisible()
  await page.getByRole('combobox', { name: 'Language', exact: true }).selectOption('de')
  await expect(page.getByText('Bitte gib einen gültigen Party-Code ein')).toBeVisible()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await expect(page.getByRole('combobox', { name: 'Sprache', exact: true })).toBeVisible()
})
