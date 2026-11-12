import { expect, test, type Page } from '@playwright/test'

async function becomeAdminHost(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Create Party', exact: true }).click()
  await page.getByPlaceholder('Your name (optional)').fill('Alice')
  await page.getByRole('button', { name: 'Join', exact: true }).click()
  await page.getByRole('main').getByRole('button', { name: 'Login to Become Host', exact: true }).click()
  await page.getByPlaceholder('Emby username').fill('Alice')
  await page.getByPlaceholder('Emby password').fill('password')
  await page.getByRole('button', { name: 'Become Host', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Admin', exact: true })).toBeVisible()
}

test('host recovery waits for post-bind status before the socket handshake', async ({ page }) => {
  await becomeAdminHost(page)
  let release!: () => void
  const delayed = new Promise<void>((resolve) => { release = resolve })
  let requests = 0
  let statusCaptured = false
  let sockets = 0
  page.on('websocket', socket => {
    if (socket.url().includes('/socket.io/')) sockets++
  })
  await page.route('**/api/v2/auth/status', async (route) => {
    // Startup owns the first read. The second belongs to the completed HTTP
    // bind and must finish before Socket.IO captures the resulting cookie.
    if (++requests !== 2) {
      await route.continue()
      return
    }
    const response = await route.fetch()
    const snapshot = await response.json() as Record<string, unknown>
    statusCaptured = true
    await delayed
    await route.fulfill({
      response,
      headers: { ...response.headers(), 'x-issue74-delayed': 'true' },
      json: { ...snapshot, party_unlocked: false },
    })
  })

  try {
    await page.reload({ waitUntil: 'domcontentloaded' })
    const library = page.getByRole('button', { name: 'Browse Library', exact: true }).first()
    await expect.poll(() => statusCaptured).toBe(true)
    await expect(page.locator('.join-spinner')).toBeVisible()
    await expect(page.getByPlaceholder('Your name (optional)')).toBeHidden()
    expect(sockets).toBe(0)
    const delivered = page.waitForResponse((response) => response.headers()['x-issue74-delayed'] === 'true')
    release()
    await (await delivered).finished()
    // The pre-presence snapshot is intentionally locked. The fresh socket
    // must restore the host after that response, without a second reload.
    await page.evaluate(() => new Promise<void>((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(() => resolve()))
    }))
    await expect(library).toBeVisible()
    await expect(page.getByRole('main').getByRole('button', { name: 'Login to Become Host', exact: true })).toBeHidden()
    await expect(page.getByRole('button', { name: 'Admin', exact: true })).toBeVisible()
  } finally {
    release()
  }
})

for (const failure of [
  { name: 'temporary server failure', status: 503, body: JSON.stringify({ detail: 'Settings temporarily unavailable' }), contentType: 'application/json' },
  { name: 'HTML returned with HTTP 200', status: 200, body: '<html>Proxy response</html>', contentType: 'text/html' },
]) {
  test(`admin settings stay open and retry after ${failure.name}`, async ({ page }) => {
    await becomeAdminHost(page)
    let first = true
    await page.route('**/api/admin/config', async (route) => {
      if (!first) {
        await route.continue()
        return
      }
      first = false
      await route.fulfill({ status: failure.status, body: failure.body, contentType: failure.contentType })
    })

    await page.getByRole('button', { name: 'Admin', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: 'Admin Panel', exact: true })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByRole('alert')).toBeVisible()
    await expect(dialog.getByRole('button', { name: 'Save Settings', exact: true })).toBeDisabled()
    await dialog.getByRole('button', { name: 'Retry', exact: true }).click()
    await expect(dialog.getByRole('alert')).toBeHidden()
    await expect(dialog.getByRole('button', { name: 'Save Settings', exact: true })).toBeEnabled()
    await expect(dialog.getByLabel('Admin Login Limit window', { exact: true })).toHaveValue('per 15 minutes')
    await expect(page.getByRole('button', { name: 'Admin', exact: true })).toBeVisible()
  })
}
