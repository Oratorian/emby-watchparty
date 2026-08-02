import { expect, test } from '@playwright/test'

test('host authenticates and browses the fake Emby library', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Create Party', exact: true }).click()
  await page.getByPlaceholder('Your name (optional)').fill('Alice')
  await page.getByRole('button', { name: 'Join', exact: true }).click()

  await page.getByRole('main').getByRole(
    'button', { name: 'Login to Become Host', exact: true },
  ).click()
  await page.getByPlaceholder('Emby username').fill('Alice')
  await page.getByPlaceholder('Emby password').fill('password')
  await page.getByRole('button', { name: 'Become Host', exact: true }).click()

  await expect(page.getByRole('button', { name: 'Browse Library', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Browse Library', exact: true }).click()
  await expect(page.getByText('Fake Movie', { exact: true })).toBeVisible()
})
