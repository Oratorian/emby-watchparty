import { expect, test } from '@playwright/test'

test('iOS viewport supports safe areas and party controls remain usable', async ({ page }) => {
  await page.goto('/')

  const viewport = await page.locator('meta[name="viewport"]').getAttribute('content')
  expect(viewport).toContain('viewport-fit=cover')
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
    await page.evaluate(() => document.documentElement.clientWidth),
  )

  await page.getByRole('button', { name: 'Create Party', exact: true }).tap()
  await page.getByPlaceholder('Your name (optional)').fill('iPhone Guest')
  await page.getByRole('button', { name: 'Join', exact: true }).tap()

  await expect(page.getByText('1 watching')).toBeVisible()
  await page.getByRole('button', { name: 'Chat', exact: true }).tap()
  await expect(page.getByRole('heading', { name: 'Chat' })).toBeVisible()
  await expect(page.getByTitle('Close chat')).toBeVisible()
})
