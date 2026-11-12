import { expect, test, type Page } from '@playwright/test'

async function openShow(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Create Party', exact: true }).click()
  await page.getByPlaceholder('Your name (optional)').fill('Preview viewer')
  await page.getByRole('button', { name: 'Join', exact: true }).click()
  await page.getByRole('main').getByRole('button', { name: 'Login to Become Host', exact: true }).click()
  await page.getByPlaceholder('Emby username').fill('PreviewViewer')
  await page.getByPlaceholder('Emby password').fill('password')
  await page.getByRole('button', { name: 'Become Host', exact: true }).click()
  await page.getByRole('button', { name: 'Open TV Shows', exact: true }).click()
  await page.getByRole('button', { name: 'Open Preview Series', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Preview Series', exact: true })).toBeVisible()
}

async function openMovie(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Create Party', exact: true }).click()
  await page.getByPlaceholder('Your name (optional)').fill('Movie preview viewer')
  await page.getByRole('button', { name: 'Join', exact: true }).click()
  await page.getByRole('main').getByRole('button', { name: 'Login to Become Host', exact: true }).click()
  await page.getByPlaceholder('Emby username').fill('Alice')
  await page.getByPlaceholder('Emby password').fill('password')
  await page.getByRole('button', { name: 'Become Host', exact: true }).click()
  await page.getByRole('button', { name: 'Open Movies', exact: true }).click()
  await page.getByRole('button', { name: 'Open Fake Movie', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Fake Movie', exact: true })).toBeVisible()
}

test.use({ viewport: { width: 1600, height: 900 }, locale: 'en-US' })

test('a show background starts muted, can be unmuted and releases its isolated stream', async ({ page, browserName, request }) => {
  test.skip(browserName !== 'chromium', 'Chromium owns the fake-Emby media playback checks.')
  const creation = page.waitForResponse(response => response.url().endsWith('/api/v2/items/series-1/preview'))
  await openShow(page)
  const response = await creation
  expect(response.status()).toBe(201)
  const lease = await response.json() as { preview_id: string; url: string; duration_seconds: number }
  expect(lease.duration_seconds).toBe(120)
  expect(lease.url).toContain('/api/v2/previews/')
  expect(lease.url).not.toMatch(/fake-access-token|127\.0\.0\.1:5012/)
  const video = page.locator('.show-preview-video')
  await expect(page.getByRole('button', { name: 'Pause preview', exact: true })).toBeVisible({ timeout: 15_000 })
  await expect(video).toHaveJSProperty('muted', true)
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.readyState)).toBeGreaterThanOrEqual(2)
  await expect(video).toHaveClass(/is-playing/)
  await expect(page.getByRole('button', { name: 'Browse seasons', exact: true })).toBeVisible()
  await expect(page.locator('video#videoElement')).toHaveCount(0)
  await page.getByRole('button', { name: 'Unmute preview', exact: true }).click()
  await expect(video).toHaveJSProperty('muted', false)
  await page.getByRole('button', { name: 'Mute preview', exact: true }).click()
  await expect(video).toHaveJSProperty('muted', true)
  const released = page.waitForResponse(result => result.request().method() === 'DELETE'
    && result.url().endsWith(`/api/v2/previews/${lease.preview_id}`))
  await page.locator('button.back-to-library').click()
  expect((await released).status()).toBe(204)
  await expect(video).toHaveCount(0)
  expect((await page.request.get(lease.url)).status()).toBe(404)

  const upstream = await request.get('http://127.0.0.1:5012/__test__/requests')
  const recorded = (await upstream.json()).requests as Array<{
    method: string; path: string; query: Array<[string, string]>; body?: { PlaySessionId?: string }
  }>
  const masters = recorded.filter(row => row.path === '/emby/Videos/episode-1/master.m3u8')
  expect(masters.length).toBeGreaterThan(0)
  const params = new URLSearchParams(masters.at(-1)!.query)
  expect(params.get('EnableAutoStreamCopy')).toBe('false')
  expect(params.get('MaxWidth')).toBe('640')
  expect(params.get('MaxHeight')).toBe('360')
  expect(params.get('VideoBitrate')).toBe('750000')
  const session = params.get('PlaySessionId')!
  expect(recorded.some(row => row.method === 'DELETE' && row.path === '/emby/Videos/ActiveEncodings'
    && new URLSearchParams(row.query).get('PlaySessionId') === session)).toBe(true)
  expect(recorded.some(row => row.path.startsWith('/emby/Sessions/Playing')
    && row.body?.PlaySessionId === session)).toBe(false)
})

test('a movie background autoplays muted without starting party playback', async ({ page, browserName }) => {
  test.skip(browserName !== 'chromium', 'Chromium owns the fake-Emby media playback checks.')
  const creation = page.waitForResponse(response => response.url().endsWith('/api/v2/items/movie-1/preview'))
  await openMovie(page)
  const response = await creation
  expect(response.status()).toBe(201)
  const lease = await response.json() as { preview_id: string; url: string; duration_seconds: number }
  expect(lease.duration_seconds).toBe(120)
  expect(lease.url).toContain('/api/v2/previews/')
  expect(lease.url).not.toMatch(/fake-access-token|127\.0\.0\.1:5012/)
  const group = page.getByRole('group', { name: 'Background preview', exact: true })
  const video = group.locator('.show-preview-video')
  await expect(group.getByRole('button', { name: 'Pause preview', exact: true })).toBeVisible({ timeout: 15_000 })
  await expect(video).toHaveJSProperty('muted', true)
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.readyState)).toBeGreaterThanOrEqual(2)
  await expect(video).toHaveClass(/is-playing/)
  await expect(page.getByRole('button', { name: 'Set up playback', exact: true })).toBeVisible()
  await expect(page.locator('video#videoElement')).toHaveCount(0)

  await group.getByRole('button', { name: 'Unmute preview', exact: true }).click()
  await expect(video).toHaveJSProperty('muted', false)
  await group.getByRole('button', { name: 'Pause preview', exact: true }).click()
  await expect(video).toHaveJSProperty('paused', true)
  await group.getByRole('button', { name: 'Play preview', exact: true }).click()
  await expect(group.getByRole('button', { name: 'Pause preview', exact: true })).toBeVisible()
  await expect(video).toHaveJSProperty('muted', false)
  await expect(page.locator('video#videoElement')).toHaveCount(0)

  const released = page.waitForResponse(result => result.request().method() === 'DELETE'
    && result.url().endsWith(`/api/v2/previews/${lease.preview_id}`))
  await page.getByRole('banner').getByRole('button', { name: 'Hide Library', exact: true }).click()
  expect((await released).status()).toBe(204)
  await expect(page.locator('.show-preview-video')).toHaveCount(0)
  await expect(page.locator('video#videoElement')).toHaveCount(0)
  await expect(page.getByRole('heading', { name: 'No video selected', exact: true })).toBeVisible()
  expect((await page.request.get(lease.url)).status()).toBe(404)
})

test('autoplay refusal offers an explicit play action without enabling audio', async ({ page, browserName }) => {
  test.skip(browserName !== 'chromium', 'Uses the fake-Emby HLS media boundary.')
  await page.addInitScript(() => {
    const original = HTMLMediaElement.prototype.play
    let refused = false
    HTMLMediaElement.prototype.play = function () {
      if (this.classList.contains('show-preview-video') && !refused) {
        refused = true
        return Promise.reject(new DOMException('Autoplay denied', 'NotAllowedError'))
      }
      return original.call(this)
    }
  })
  await openShow(page)
  const group = page.getByRole('group', { name: 'Background preview', exact: true })
  await expect(group.getByRole('button', { name: 'Unmute preview', exact: true })).toBeVisible({ timeout: 15_000 })
  await expect(group.getByRole('button', { name: 'Play preview', exact: true })).toBeVisible()
  await expect(page.locator('.show-preview-video')).toHaveJSProperty('muted', true)
  await group.getByRole('button', { name: 'Play preview', exact: true }).click()
  await expect(group.getByRole('button', { name: 'Pause preview', exact: true })).toBeVisible()
  await expect(page.locator('.show-preview-video')).toHaveJSProperty('muted', true)
})

test('reduced motion keeps the still backdrop without creating an automatic preview', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  let requests = 0
  page.on('request', request => {
    if (request.method() === 'POST' && request.url().endsWith('/items/series-1/preview')) requests++
  })
  await openShow(page)
  await expect(page.getByRole('group', { name: 'Background preview', exact: true })
    .getByRole('button', { name: 'Play preview', exact: true })).toBeVisible()
  await page.waitForTimeout(1100)
  expect(requests).toBe(0)
  await expect(page.locator('.show-preview-video')).not.toHaveClass(/is-playing/)
})
