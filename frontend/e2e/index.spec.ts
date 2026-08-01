import { expect, test } from '@playwright/test'

test('landing page validates an empty party code', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Emby Watch Party' })).toBeVisible()
  await page.getByRole('button', { name: 'Join', exact: true }).click()
  await expect(page.getByText('Please enter a valid party code')).toBeVisible()
})

test('host creates party and a second browser joins', async ({ browser, page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Create Party', exact: true }).click()
  await expect(page).toHaveURL(/\/party\/[A-Z0-9]+$/)
  const partyUrl = page.url()
  await page.getByPlaceholder('Your name (optional)').fill('Alice')
  await page.getByRole('button', { name: 'Join', exact: true }).click()
  await expect(page.getByText('1 watching')).toBeVisible()

  const guestContext = await browser.newContext()
  const guest = await guestContext.newPage()
  await guest.goto(partyUrl)
  await guest.getByPlaceholder('Your name (optional)').fill('Bob')
  await guest.getByRole('button', { name: 'Join', exact: true }).click()

  await expect(page.getByText('2 watching')).toBeVisible()
  await expect(guest.getByText('2 watching')).toBeVisible()
  await guestContext.close()
})
