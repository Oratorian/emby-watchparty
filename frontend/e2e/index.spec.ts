import { expect, test } from '@playwright/test'

test.beforeEach(async ({ page }) => {
  await page.route('**/*', async route => {
    const path = new URL(route.request().url()).pathname
    if (!path.startsWith('/api/')) {
      await route.continue()
      return
    }
    let body: object = {}
    if (path.endsWith('/auth/status')) {
      body = {
        authenticated: false,
        is_admin: false,
        require_login: false,
        is_host: false,
        party_id: null,
        host_username: null,
        party_unlocked: false,
      }
    } else if (path.endsWith('/party/static-session')) {
      body = { party_id: null }
    } else if (path.endsWith('/party/list')) {
      body = { require_login: false, parties: [] }
    }
    await route.fulfill({ json: body })
  })
})

test('landing page validates an empty party code', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Emby Watch Party' })).toBeVisible()
  await page.getByRole('button', { name: 'Join', exact: true }).click()
  await expect(page.getByText('Please enter a valid party code')).toBeVisible()
})
