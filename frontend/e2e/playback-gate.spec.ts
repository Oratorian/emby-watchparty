import { expect, test, type APIResponse, type Page } from '@playwright/test'

function mediaUri(playlist: string): string {
  const value = playlist.split(/\r?\n/).find((line) => line && !line.startsWith('#'))
  if (!value) throw new Error('Playlist contained no media URI')
  return value
}

async function createAndJoin(page: Page, name: string): Promise<string> {
  await page.goto('/')
  await page.getByRole('button', { name: 'Create Party', exact: true }).click()
  await expect(page).toHaveURL(/\/party\/[A-Z0-9]+$/)
  const partyUrl = page.url()
  await page.getByPlaceholder('Your name (optional)').fill(name)
  await page.getByRole('button', { name: 'Join', exact: true }).click()
  await expect(page.getByText('1 watching')).toBeVisible()
  return partyUrl
}

async function loginAndSelectMovie(page: Page): Promise<void> {
  await page.getByRole('main').getByRole(
    'button', { name: 'Login to Become Host', exact: true },
  ).click()
  await page.getByPlaceholder('Emby username').fill('Alice')
  await page.getByPlaceholder('Emby password').fill('password')
  await page.getByRole('button', { name: 'Become Host', exact: true }).click()
  await page.getByText('Movies', { exact: true }).click()
  await page.getByText('Fake Movie', { exact: true }).click()
  await expect(page.locator('video#videoElement')).toHaveAttribute('title', 'Fake Movie')
}

async function expectOk(response: APIResponse, label: string): Promise<void> {
  expect(response.status(), `${label} returned ${response.status()}`).toBe(200)
}

test('@playback-gate complete authenticated fake-Emby playback flow', async ({ browser, page }) => {
  const watchedFailures: string[] = []
  const masterRequests: string[] = []
  let expectedBindLimit = false
  const audit = (response: APIResponse) => {
    if (![401, 403, 429].includes(response.status())) return
    if (expectedBindLimit && response.status() === 429 && response.url().includes('/join')) return
    watchedFailures.push(`${response.status()} ${response.url()}`)
  }
  page.on('response', audit)
  page.on('request', (request) => {
    if (request.url().includes('/hls/movie-1/master.m3u8')) {
      masterRequests.push(request.url())
    }
  })

  const ready = await page.request.get('/api/ready')
  await expectOk(ready, 'readiness')
  const partyUrl = await createAndJoin(page, 'Alice')

  const guestContext = await browser.newContext()
  const guest = await guestContext.newPage()
  guest.on('response', audit)
  await guest.goto(partyUrl)
  await guest.getByPlaceholder('Your name (optional)').fill('Bob')
  await guest.getByRole('button', { name: 'Join', exact: true }).click()
  await expect(page.getByText('2 watching')).toBeVisible()

  await loginAndSelectMovie(page)
  const hostVideo = page.locator('video#videoElement')
  const guestVideo = guest.locator('video#videoElement')
  await expect(guestVideo).toHaveAttribute('title', 'Fake Movie')

  await page.waitForFunction(() => {
    const video = document.querySelector<HTMLVideoElement>('video#videoElement')
    return video && video.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA
  })
  await hostVideo.focus()
  await hostVideo.press('Space')
  await expect(guest.getByText('Alice started playback')).toBeVisible()
  await page.waitForTimeout(600)
  await hostVideo.press('Space')
  await expect(guest.getByText('Alice paused playback')).toBeVisible()

  await page.getByRole('button', { name: '+10s' }).click()
  await expect(guest.getByText(/Alice seeked to/)).toBeVisible()
  const forwardTime = await guestVideo.evaluate((video: HTMLVideoElement) => video.currentTime)
  await page.getByRole('button', { name: '−10s' }).click()
  await expect.poll(
    () => guestVideo.evaluate((video: HTMLVideoElement) => video.currentTime),
  ).toBeLessThan(forwardTime)

  await expect.poll(() => masterRequests.length).toBeGreaterThan(0)
  const masterUrl = masterRequests.at(-1)!
  const master = await page.request.get(masterUrl)
  await expectOk(master, 'authenticated HLS master playlist')
  expect(master.headers()['content-type']).toContain('mpegurl')
  const variantUrl = new URL(mediaUri(await master.text()), masterUrl).href
  const variant = await page.request.get(variantUrl)
  await expectOk(variant, 'authenticated HLS media playlist')
  const segmentUrl = new URL(mediaUri(await variant.text()), variantUrl).href
  const segment = await page.request.get(segmentUrl)
  await expectOk(segment, 'authenticated HLS segment')
  expect((await segment.body()).byteLength).toBeGreaterThan(0)
  const range = await page.request.get(segmentUrl, { headers: { Range: 'bytes=0-17' } })
  expect(range.status()).toBe(206)
  expect(range.headers()['content-range']).toBe('bytes 0-17/168260')
  expect((await range.body()).byteLength).toBe(18)

  const audio = page.getByLabel('Audio')
  await expect(audio.locator('option')).toHaveCount(2)
  const sourceBeforeAudio = await hostVideo.getAttribute('src')
  await audio.selectOption('2')
  await expect(audio).toHaveValue('2')
  await expect.poll(() => hostVideo.getAttribute('src')).not.toBe(sourceBeforeAudio)

  const subtitles = page.getByLabel('Subtitles')
  await expect(subtitles.locator('option')).toHaveCount(2)
  await subtitles.selectOption('3')
  await expect(subtitles).toHaveValue('3')
  await expect.poll(
    () => page.locator('video#videoElement track[kind="subtitles"]').count(),
  ).toBe(1)

  const sourceBeforeReconnect = await guestVideo.getAttribute('src')
  await guestContext.setOffline(true)
  await guest.evaluate(() => window.dispatchEvent(new Event('offline')))
  await expect(guest.getByText('Reconnecting to party…')).toBeVisible()
  await guestContext.setOffline(false)
  await guest.evaluate(() => window.dispatchEvent(new Event('online')))
  await expect(guest.getByText('Reconnecting to party…')).toBeHidden({ timeout: 15_000 })
  await expect.poll(() => guestVideo.getAttribute('src')).not.toBe(sourceBeforeReconnect)
  await expect(guest.getByText('2 watching')).toBeVisible()

  let rejectedBind = false
  await page.route('**/api/party/*/join', async (route) => {
    if (rejectedBind) return route.continue()
    rejectedBind = true
    expectedBindLimit = true
    return route.fulfill({
      status: 429,
      headers: { 'content-type': 'application/json', 'retry-after': '1' },
      body: JSON.stringify({
        detail: 'Too many party joins. Try again in 1 seconds.',
        code: 'rate_limited',
        retry_after: 1,
      }),
    })
  })
  await page.reload()
  await expect(page.getByText(/Too many party joins/)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Retry' })).toBeEnabled({ timeout: 3_000 })
  await page.getByRole('button', { name: 'Retry' }).click()
  expectedBindLimit = false
  await expect(page.getByText(/Too many party joins/)).toBeHidden()
  await expect(page.getByText('2 watching')).toBeVisible()
  await expect(page.locator('video#videoElement')).toHaveAttribute('title', 'Fake Movie')

  const otherContext = await browser.newContext()
  const created = await otherContext.request.post('/api/party/create', { data: {} })
  expect(created.status()).toBe(200)
  const otherParty = (await created.json()).party_id as string
  const joined = await otherContext.request.post(`/api/party/${otherParty}/join`, {
    data: { client_id: 'cross-party-client', display_name: 'Mallory' },
  })
  expect(joined.status()).toBe(200)
  const otherLogin = await otherContext.request.post('/api/auth/login', {
    data: { username: 'Mallory', password: 'password' },
  })
  expect(otherLogin.status()).toBe(200)
  expect((await otherLogin.json()).success).toBe(true)
  const denied = await otherContext.request.get(masterUrl)
  expect([401, 403]).toContain(denied.status())

  expect(watchedFailures, 'unexpected auth, rate-limit, or cross-party browser failures').toEqual([])
  await otherContext.close()
  await guestContext.close()
})
