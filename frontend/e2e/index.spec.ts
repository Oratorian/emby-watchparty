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
  const joinClientIds: string[] = []
  let rejectReservedIdentity = true
  await guest.route('**/api/party/*/join', async (route) => {
    const body = route.request().postDataJSON() as { client_id: string }
    joinClientIds.push(body.client_id)
    if (rejectReservedIdentity) {
      rejectReservedIdentity = false
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          success: false,
          message: 'Participant identity is already in use',
        }),
      })
      return
    }
    await route.continue()
  })
  await guest.goto(partyUrl)
  await guest.getByPlaceholder('Your name (optional)').fill('Bob')
  await guest.getByRole('button', { name: 'Join', exact: true }).click()

  await expect(page.getByText('2 watching')).toBeVisible()
  await expect(guest.getByText('2 watching')).toBeVisible()
  expect([...new Set(joinClientIds)]).toHaveLength(2)

  await page.context().setOffline(true)
  await page.evaluate(() => window.dispatchEvent(new Event('offline')))
  await expect(page.getByText('Reconnecting to party…')).toBeVisible()
  await page.context().setOffline(false)
  await page.evaluate(() => window.dispatchEvent(new Event('online')))
  await expect(page.getByText('Reconnecting to party…')).toBeHidden({ timeout: 15_000 })
  await expect(page.getByText('2 watching')).toBeVisible()
  await guestContext.close()
})

test('mobile lifecycle remains keyboard accessible with reduced motion', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')

  const code = page.getByPlaceholder('Party code')
  await code.focus()
  await code.fill('')
  await code.press('Enter')
  await expect(page.getByText('Please enter a valid party code')).toBeVisible()
  const create = page.getByRole('button', { name: 'Create Party', exact: true })
  await expect(create).toBeVisible()
  await expect(create).toHaveCSS('transition-duration', '0s')
})
