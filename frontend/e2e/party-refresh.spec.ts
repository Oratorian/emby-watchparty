import { randomUUID } from 'node:crypto'
import { expect, test, type APIRequestContext, type Page } from '@playwright/test'

const devHostURL = 'http://127.0.0.1:4174'
const usernameKey = 'emby-watchparty-username'
const clientKey = 'emby-watchparty-client-id'

// The container journey intentionally tests its own production image. This
// regression needs a separate source backend with an explicitly synthetic dev gate.
test.skip(Boolean(process.env.E2E_BASE_URL), 'Requires the isolated dev-host browser fixture.')
test.use({ viewport: { width: 1440, height: 900 }, locale: 'en-US' })

async function createParty(request: APIRequestContext): Promise<string> {
  const response = await request.post(`${devHostURL}/api/party/create`, { data: {} })
  expect(response.ok()).toBe(true)
  const created = await response.json() as { party_id: string }
  expect(created.party_id).toMatch(/^[A-Z0-9]+$/)
  return created.party_id
}

async function expectJoinedHost(page: Page, partyId: string) {
  await expect(page.locator('.party-container')).toBeVisible()
  await expect(page.getByText('1 watching', { exact: true })).toBeVisible()
  await expect(page.getByPlaceholder('Your name (optional)')).toBeHidden()
  await expect(page.getByRole('button', { name: 'Admin', exact: true })).toBeVisible()
  const response = await page.request.get(`${devHostURL}/api/v2/auth/status`)
  expect(response.ok()).toBe(true)
  expect(await response.json()).toMatchObject({ is_host: true, is_admin: true, party_id: partyId })
}

test('a first manual join connects using the host grant minted by HTTP binding', async ({ page, request }) => {
  const partyId = await createParty(request)
  const ordering: string[] = []
  page.on('response', response => {
    if (response.url().endsWith(`/api/party/${partyId}/join`) && response.ok()) ordering.push('bound')
  })
  page.on('websocket', socket => {
    if (socket.url().includes('/socket.io/')) ordering.push('socket')
  })
  await page.goto(`${devHostURL}/party/${partyId}`)
  await page.getByPlaceholder('Your name (optional)').fill('Alice')
  await page.getByRole('button', { name: 'Join', exact: true }).click()
  await expectJoinedHost(page, partyId)

  expect(ordering.indexOf('bound')).toBeGreaterThanOrEqual(0)
  expect(ordering.indexOf('socket')).toBeGreaterThan(ordering.indexOf('bound'))
  expect(await page.evaluate(key => localStorage.getItem(key), usernameKey)).toBe('Alice')
})

test('each refresh restores the saved host once without revealing the username prompt', async ({ page, request }) => {
  const partyId = await createParty(request)
  const clientId = randomUUID()
  // Seed a valid host cookie without an existing socket. This isolates the
  // refresh defect from the separate cold manual-join regression above.
  const binding = await page.request.post(`${devHostURL}/api/party/${partyId}/join`, {
    data: { client_id: clientId, display_name: 'Alice' },
  })
  expect(binding.ok()).toBe(true)
  expect(await binding.json()).toMatchObject({ success: true, is_host: true })
  await page.addInitScript(({ nameKey, identityKey, identity }) => {
    localStorage.setItem(nameKey, 'Alice')
    localStorage.setItem(identityKey, identity)
    const state = window as Window & { __ewpUsernamePromptSeen?: boolean }
    state.__ewpUsernamePromptSeen = false
    new MutationObserver(() => {
      if (document.querySelector('input[placeholder="Your name (optional)"]')) {
        state.__ewpUsernamePromptSeen = true
      }
    }).observe(document, { childList: true, subtree: true })
  }, { nameKey: usernameKey, identityKey: clientKey, identity: clientId })
  await page.goto(`${devHostURL}/party/${partyId}`)
  await expectJoinedHost(page, partyId)

  for (let refresh = 0; refresh < 3; refresh++) {
    await page.reload({ waitUntil: 'domcontentloaded' })
    await expectJoinedHost(page, partyId)
    expect(await page.evaluate(() => (window as Window & {
      __ewpUsernamePromptSeen?: boolean
    }).__ewpUsernamePromptSeen)).toBe(false)
    expect(await page.evaluate(key => localStorage.getItem(key), usernameKey)).toBe('Alice')
  }
})
