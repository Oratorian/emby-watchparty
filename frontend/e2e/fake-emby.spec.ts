import { expect, test, type Page } from '@playwright/test'

async function startFakeMovie(page: Page): Promise<void> {
  await page.getByText('Fake Movie', { exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Fake Movie', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Play', exact: true }).click()
  await page.getByRole('button', { name: 'Start watch party', exact: true }).click()
  await expect(page.locator('video#videoElement')).toHaveAttribute('title', 'Fake Movie')
}

test('party host login shows backend rate-limit detail', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Create Party', exact: true }).click()
  await page.getByPlaceholder('Your name (optional)').fill('Alice')
  await page.getByRole('button', { name: 'Join', exact: true }).click()
  await page.getByRole('main').getByRole(
    'button', { name: 'Login to Become Host', exact: true },
  ).click()
  await page.getByPlaceholder('Emby username').fill('Alice')
  await page.getByPlaceholder('Emby password').fill('password')
  await page.route('**/api/v2/auth/login', (route) => route.fulfill({
    status: 429,
    headers: { 'content-type': 'application/json', 'retry-after': '7' },
    body: JSON.stringify({
      detail: 'Too many login attempts. Try again in 7 seconds.',
      code: 'rate_limited',
      retry_after: 7,
    }),
  }))

  await page.getByRole('button', { name: 'Become Host', exact: true }).click()

  await expect(page.getByText('Too many login attempts. Try again in 7 seconds.')).toBeVisible()
})

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

  await expect(page.getByRole('heading', { name: 'Choose a library' })).toBeVisible()
  await expect(page.getByText('CollectionFolder', { exact: true })).toBeHidden()
  const libraryArtwork = page.getByRole('button', { name: 'Open Movies', exact: true })
    .locator('.item-poster')
  await expect(libraryArtwork.getByText('MOVIES', { exact: true })).toBeVisible()
  expect(await libraryArtwork.evaluate((element) => {
    const box = element.getBoundingClientRect()
    return box.width / box.height
  })).toBeGreaterThan(1.5)
  const librarySearch = page.getByRole('searchbox', { name: 'Search all libraries' })
  const searchMetrics = await librarySearch.evaluate((element) => {
    const box = element.getBoundingClientRect()
    return { fontSize: Number.parseFloat(getComputedStyle(element).fontSize), height: box.height }
  })
  expect(searchMetrics.fontSize).toBeGreaterThanOrEqual(14)
  expect(searchMetrics.height).toBeGreaterThanOrEqual(40)

  await page.setViewportSize({ width: 390, height: 844 })
  const compactSearchMetrics = await librarySearch.evaluate((element) => {
    const box = element.getBoundingClientRect()
    return { fontSize: Number.parseFloat(getComputedStyle(element).fontSize), height: box.height }
  })
  expect(compactSearchMetrics.fontSize).toBeGreaterThanOrEqual(14)
  expect(compactSearchMetrics.height).toBeGreaterThanOrEqual(40)
  await page.setViewportSize({ width: 1280, height: 720 })

  await page.getByText('Movies', { exact: true }).click()
  const movie = page.getByText('Fake Movie', { exact: true })
  await expect(movie).toBeVisible()
  await startFakeMovie(page)
})

test('host filters, opens details, configures playback, and restores library state', async ({ page }) => {
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
  await page.getByText('Movies', { exact: true }).click()

  await page.getByRole('button', { name: 'Filters', exact: true }).click()
  await page.getByRole('button', { name: 'Open Genre filter', exact: true }).click()
  await page.getByLabel('Drama', { exact: true }).check()
  await expect(page.getByText('Genre: Drama', { exact: true })).toBeVisible()

  const movieCard = page.getByRole('button', { name: 'Open Fake Movie', exact: true })
  await movieCard.focus()
  await movieCard.press('Enter')
  await expect(page.getByRole('heading', { name: 'Fake Movie', exact: true })).toBeVisible()
  await expect(page.getByText('A deterministic movie served by fake Emby.')).toBeVisible()
  await page.getByRole('button', { name: 'Favorite', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Remove favorite', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Mark played', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Mark unplayed', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Add to playlist', exact: true }).click()
  await page.getByLabel('Playlist', { exact: true }).selectOption('playlist-1')
  await page.getByRole('button', { name: 'Add', exact: true }).click()
  await expect(page.getByLabel('Playlist', { exact: true })).toBeHidden()

  await page.getByRole('button', { name: 'Play', exact: true }).click()
  await expect(page.getByLabel('Quality', { exact: true })).toBeVisible()
  await expect(page.getByLabel('Audio', { exact: true }).locator('option')).toHaveCount(2)
  await expect(page.getByLabel('Subtitles', { exact: true }).locator('option')).toHaveCount(2)

  await page.getByRole('button', { name: '← Back', exact: true }).click()
  await expect(page.getByText('Genre: Drama', { exact: true })).toBeVisible()
  await expect(movieCard).toBeFocused()

  const search = page.getByLabel('Search all libraries')
  await search.fill('Fake Movie')
  await search.press('Enter')
  await expect(page.getByRole('heading', { name: 'Movies', exact: true })).toBeVisible()
  await expect(page.locator('.search-results').getByRole('button', { name: 'Fake Movie' }).first()).toBeVisible()
  await page.getByRole('button', { name: 'Reset All', exact: true }).click()
  await expect(page.getByText('Genre: Drama', { exact: true })).toBeHidden()
})

test('large library stays bounded and search remains responsive', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Create Party', exact: true }).click()
  await page.getByPlaceholder('Your name (optional)').fill('Alice')
  await page.getByRole('button', { name: 'Join', exact: true }).click()

  await page.getByRole('main').getByRole(
    'button', { name: 'Login to Become Host', exact: true },
  ).click()
  await page.getByPlaceholder('Emby username').fill('LargeLibrary')
  await page.getByPlaceholder('Emby password').fill('password')
  await page.getByRole('button', { name: 'Become Host', exact: true }).click()
  await page.getByText('Movies', { exact: true }).click()
  await expect(page.getByText('Large Movie 0000', { exact: true })).toBeVisible()

  await page.waitForTimeout(500)
  expect(await page.locator('.item-card').count()).toBeLessThanOrEqual(100)

  const search = page.getByLabel('Search all libraries')
  await search.fill('Large Movie 0420')
  await search.press('Enter')
  await expect(page.getByRole('button', { name: 'Clear', exact: true })).toBeVisible()
  await expect(page.locator('.search-results').getByRole(
    'button', { name: 'Large Movie 0420', exact: true },
  ).first()).toBeVisible()
  expect(await page.locator('.item-card').count()).toBeLessThanOrEqual(100)
})

test('alphabet bar jumps across an unloaded library and can scroll back', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Create Party', exact: true }).click()
  await page.getByPlaceholder('Your name (optional)').fill('Alice')
  await page.getByRole('button', { name: 'Join', exact: true }).click()
  await page.getByRole('main').getByRole(
    'button', { name: 'Login to Become Host', exact: true },
  ).click()
  await page.getByPlaceholder('Emby username').fill('AlphabetLibrary')
  await page.getByPlaceholder('Emby password').fill('password')
  await page.getByRole('button', { name: 'Become Host', exact: true }).click()
  await page.getByText('Movies', { exact: true }).click()

  const middle = page.getByRole('button', { name: 'Jump to M', exact: true })
  await expect(middle).toBeEnabled()
  await middle.click()
  const middleMovie = page.getByText('Middle Movie 0000', { exact: true })
  await expect(middleMovie).toBeVisible()
  await page.waitForTimeout(500)
  expect(await middleMovie.evaluate((item) => {
    const rect = item.getBoundingClientRect()
    return rect.bottom > 0 && rect.top < window.innerHeight
  })).toBe(true)
  expect(await page.locator('.item-card').count()).toBeLessThanOrEqual(100)

  await page.locator('.library-panel').evaluate((panel) => panel.scrollTo(0, 0))
  await expect(page.getByText('Alpha Movie 0050', { exact: true })).toBeVisible()

  const zulu = page.getByText('Zulu Movie 0000', { exact: true })
  await page.getByRole('button', { name: 'Jump to Z', exact: true }).click()
  await expect(zulu).toBeVisible()
  expect(await zulu.evaluate((item) => {
    const rect = item.getBoundingClientRect()
    return rect.bottom > 0 && rect.top < window.innerHeight
  })).toBe(true)

  const alpha = page.getByText('Alpha Movie 0000', { exact: true })
  await page.getByRole('button', { name: 'Jump to A', exact: true }).click()
  await expect(alpha).toBeVisible()
  expect(await alpha.evaluate((item) => {
    const rect = item.getBoundingClientRect()
    return rect.bottom > 0 && rect.top < window.innerHeight
  })).toBe(true)
})

test('legacy saved library state still enables alphabet navigation', async ({ page }) => {
  await page.setViewportSize({ width: 910, height: 427 })
  await page.goto('/')
  await page.getByRole('button', { name: 'Create Party', exact: true }).click()
  await page.getByPlaceholder('Your name (optional)').fill('Alice')
  await page.getByRole('button', { name: 'Join', exact: true }).click()
  await page.getByRole('main').getByRole(
    'button', { name: 'Login to Become Host', exact: true },
  ).click()
  await page.getByPlaceholder('Emby username').fill('AlphabetLibrary')
  await page.getByPlaceholder('Emby password').fill('password')
  await page.getByRole('button', { name: 'Become Host', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Open Movies', exact: true })).toBeVisible()

  await page.evaluate(() => localStorage.setItem(
    'emby-watchparty-library-state',
    JSON.stringify({
      parentId: 'library-1',
      breadcrumbs: [{ id: 'library-1', name: 'Movies' }],
    }),
  ))
  await page.getByRole('button', { name: 'Hide Library', exact: true }).click()
  await page.getByRole('banner').getByRole(
    'button', { name: 'Browse Library', exact: true },
  ).click()

  await expect(page.getByText('Movies', { exact: true }).nth(1)).toBeVisible()
  await expect(page.getByRole('button', { name: 'Jump to M', exact: true })).toBeEnabled()
  const lastPrefix = page.getByRole('button', { name: 'Jump to Z', exact: true })
  expect(await lastPrefix.evaluate((button) => button.getBoundingClientRect().bottom)).toBeLessThanOrEqual(427)
})

test('compact desktop gives video full width and moves chat into a drawer', async ({ page }) => {
  await page.setViewportSize({ width: 1138, height: 534 })
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
  await page.getByText('Movies', { exact: true }).click()
  await startFakeMovie(page)

  const chatToggle = page.getByRole('button', { name: 'Chat', exact: true })
  await expect(chatToggle).toBeVisible()
  await expect(page.locator('.chat-panel')).not.toBeInViewport()
  expect(await page.locator('.video-area').evaluate((area) => area.getBoundingClientRect().width)).toBeGreaterThan(1120)
  const videoSizing = await page.locator('.party-content').evaluate((content) => ({
    contentHeight: content.getBoundingClientRect().height,
    videoHeight: content.querySelector('video')?.getBoundingClientRect().height ?? 0,
  }))
  expect(videoSizing.videoHeight).toBeGreaterThan(videoSizing.contentHeight * 0.9)
  expect(await page.getByRole('button', { name: 'Leave', exact: true }).evaluate(
    (button) => button.getBoundingClientRect().right <= window.innerWidth,
  )).toBe(true)

  await chatToggle.click()
  await expect(page.locator('.chat-panel')).toBeInViewport()

  // The drawer's own close button, asserted by class and by effect. By role
  // and accessible name this resolved to the .chat-backdrop overlay instead,
  // which carries aria-label="Close chat" while the button's name is its
  // text -- so nothing here proved the button did anything.
  const close = page.locator('.chat-panel .chat-close-btn')
  await expect(close).toBeVisible()
  await close.click()
  await expect(page.locator('.chat-panel')).not.toBeInViewport()

  // The backdrop is the other way out, and closes the drawer too.
  await chatToggle.click()
  await expect(page.locator('.chat-panel')).toBeInViewport()
  await page.getByRole('button', { name: 'Close chat', exact: true }).click()
  await expect(page.locator('.chat-panel')).not.toBeInViewport()
})

test('full desktop keeps chat beside the video instead of in a drawer', async ({ page }) => {
  // Every other desktop spec runs at 1138px, which is inside the compact
  // block added on this branch. So the layout most people actually use --
  // anything wider than 1280 -- had no coverage at all, and widening that
  // media query to swallow the ordinary desktop would not have failed a
  // single test.
  await page.setViewportSize({ width: 1440, height: 900 })
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
  await page.getByText('Movies', { exact: true }).click()
  await startFakeMovie(page)

  // Chat is a persistent column: on screen without being asked for, and with
  // no drawer toggle or backdrop in sight.
  await expect(page.locator('.chat-panel')).toBeInViewport()
  await expect(page.getByRole('button', { name: 'Chat', exact: true })).toBeHidden()
  await expect(page.locator('.chat-backdrop')).toHaveCount(0)

  const chatWidth = await page.locator('.chat-panel').evaluate(
    (panel) => panel.getBoundingClientRect().width,
  )
  expect(chatWidth).toBeGreaterThan(300)

  // And the video gives up exactly that column rather than the full width.
  const videoWidth = await page.locator('.video-area').evaluate(
    (area) => area.getBoundingClientRect().width,
  )
  expect(videoWidth).toBeLessThan(1440 - chatWidth + 40)
})

test('two browsers receive selection and synchronized controls', async ({ browser, page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Create Party', exact: true }).click()
  await expect(page).toHaveURL(/\/party\/[A-Z0-9]+$/)
  const partyUrl = page.url()
  await page.getByPlaceholder('Your name (optional)').fill('Alice')
  await page.getByRole('button', { name: 'Join', exact: true }).click()

  const guestContext = await browser.newContext()
  const guest = await guestContext.newPage()
  await guest.goto(partyUrl)
  await guest.getByPlaceholder('Your name (optional)').fill('Bob')
  await guest.getByRole('button', { name: 'Join', exact: true }).click()
  await expect(page.getByText('2 watching')).toBeVisible()

  await page.getByRole('main').getByRole(
    'button', { name: 'Login to Become Host', exact: true },
  ).click()
  await page.getByPlaceholder('Emby username').fill('Alice')
  await page.getByPlaceholder('Emby password').fill('password')
  await page.getByRole('button', { name: 'Become Host', exact: true }).click()
  await page.getByText('Movies', { exact: true }).click()
  await startFakeMovie(page)

  await expect(guest.locator('video#videoElement')).toHaveAttribute('title', 'Fake Movie')
  await page.waitForFunction(() => {
    const video = document.querySelector<HTMLVideoElement>('video#videoElement')
    return video && video.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA
  })
  const hostVideo = page.locator('video#videoElement')
  await hostVideo.focus()
  await hostVideo.press('Space')
  await expect(guest.getByText('Alice started playback')).toBeVisible()
  await page.waitForTimeout(600)
  await hostVideo.press('Space')
  await expect(guest.getByText('Alice paused playback')).toBeVisible()

  const guestPosition = () => guest.locator('video#videoElement').evaluate(
    (video: HTMLVideoElement) => video.currentTime,
  )
  const seekForward = page.getByRole('button', { name: '+10s' })
  await seekForward.focus()
  await seekForward.press('Enter')
  await expect.poll(guestPosition).toBeGreaterThan(8)
  await expect(guest.getByText(/Alice seeked to/)).toBeVisible()

  const hostSource = await page.locator('video#videoElement').getAttribute('src')
  const guestSource = await guest.locator('video#videoElement').getAttribute('src')
  await guest.getByLabel('Quality').selectOption({ label: '720p - 2 Mbps' })
  await expect.poll(
    () => guest.locator('video#videoElement').getAttribute('src'),
  ).not.toBe(guestSource)
  await expect(page.locator('video#videoElement')).toHaveAttribute('src', hostSource ?? '')

  const chatInput = page.getByPlaceholder('Type a message...')
  await chatInput.fill('Keyboard chat')
  await chatInput.press('Enter')
  await expect(guest.getByText('Keyboard chat')).toBeVisible()

  await guestContext.close()
})

test('playback changes are announced to assistive technology', async ({ browser, page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Create Party', exact: true }).click()
  await expect(page).toHaveURL(/\/party\/[A-Z0-9]+$/)
  const partyUrl = page.url()
  await page.getByPlaceholder('Your name (optional)').fill('Alice')
  await page.getByRole('button', { name: 'Join', exact: true }).click()

  const guestContext = await browser.newContext()
  const guest = await guestContext.newPage()
  await guest.goto(partyUrl)
  await guest.getByPlaceholder('Your name (optional)').fill('Bob')
  await guest.getByRole('button', { name: 'Join', exact: true }).click()

  await page.getByRole('main').getByRole(
    'button', { name: 'Login to Become Host', exact: true },
  ).click()
  await page.getByPlaceholder('Emby username').fill('Alice')
  await page.getByPlaceholder('Emby password').fill('password')
  await page.getByRole('button', { name: 'Become Host', exact: true }).click()
  await page.getByText('Movies', { exact: true }).click()
  await startFakeMovie(page)
  await expect(guest.locator('video#videoElement')).toHaveAttribute('title', 'Fake Movie')

  await page.waitForFunction(() => {
    const video = document.querySelector<HTMLVideoElement>('video#videoElement')
    return video && video.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA
  })
  await page.locator('video#videoElement').evaluate((video: HTMLVideoElement) => video.play())

  await expect(
    guest.getByRole('status').filter({ hasText: 'Alice started playback' }),
  ).toBeVisible()
  await guestContext.close()
})

test('active viewers can approve a late joiner', async ({ browser, page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Create Party', exact: true }).click()
  await expect(page).toHaveURL(/\/party\/[A-Z0-9]+$/)
  const partyUrl = page.url()
  await page.getByPlaceholder('Your name (optional)').fill('Alice')
  await page.getByRole('button', { name: 'Join', exact: true }).click()

  const bobContext = await browser.newContext()
  const bob = await bobContext.newPage()
  await bob.goto(partyUrl)
  await bob.getByPlaceholder('Your name (optional)').fill('Bob')
  await bob.getByRole('button', { name: 'Join', exact: true }).click()

  await page.getByRole('main').getByRole(
    'button', { name: 'Login to Become Host', exact: true },
  ).click()
  await page.getByPlaceholder('Emby username').fill('Alice')
  await page.getByPlaceholder('Emby password').fill('password')
  await page.getByRole('button', { name: 'Become Host', exact: true }).click()
  await page.getByText('Movies', { exact: true }).click()
  await startFakeMovie(page)
  await expect(bob.locator('video#videoElement')).toHaveAttribute('title', 'Fake Movie')

  const charlieContext = await browser.newContext()
  const charlie = await charlieContext.newPage()
  await charlie.goto(partyUrl)
  await charlie.getByPlaceholder('Your name (optional)').fill('Charlie')
  await charlie.getByRole('button', { name: 'Join', exact: true }).click()
  await expect(charlie.getByRole('heading', { name: 'Waiting for party approval' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Charlie wants to join' })).toBeVisible()

  const daveContext = await browser.newContext()
  const dave = await daveContext.newPage()
  await dave.goto(partyUrl)
  await dave.getByPlaceholder('Your name (optional)').fill('Dave')
  await dave.getByRole('button', { name: 'Join', exact: true }).click()
  await expect(dave).toHaveURL(/\/$/)
  await expect(page.getByText('0 of 2 voted')).toBeVisible()

  await page.getByRole('button', { name: 'Accept' }).click()
  await bob.getByRole('button', { name: 'Accept' }).click()
  await expect(charlie.getByText('3 watching')).toBeVisible()
  await expect(charlie.locator('video#videoElement')).toHaveAttribute('title', 'Fake Movie')

  await daveContext.close()
  await charlieContext.close()
  await bobContext.close()
})

test('active viewers can reject a late joiner without stopping playback', async ({ browser, page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Create Party', exact: true }).click()
  await expect(page).toHaveURL(/\/party\/[A-Z0-9]+$/)
  const partyUrl = page.url()
  await page.getByPlaceholder('Your name (optional)').fill('Alice')
  await page.getByRole('button', { name: 'Join', exact: true }).click()

  const bobContext = await browser.newContext()
  const bob = await bobContext.newPage()
  await bob.goto(partyUrl)
  await bob.getByPlaceholder('Your name (optional)').fill('Bob')
  await bob.getByRole('button', { name: 'Join', exact: true }).click()
  await page.getByRole('main').getByRole(
    'button', { name: 'Login to Become Host', exact: true },
  ).click()
  await page.getByPlaceholder('Emby username').fill('Alice')
  await page.getByPlaceholder('Emby password').fill('password')
  await page.getByRole('button', { name: 'Become Host', exact: true }).click()
  await page.getByText('Movies', { exact: true }).click()
  await startFakeMovie(page)
  await expect(bob.locator('video#videoElement')).toHaveAttribute('title', 'Fake Movie')

  const charlieContext = await browser.newContext()
  const charlie = await charlieContext.newPage()
  await charlie.goto(partyUrl)
  await charlie.getByPlaceholder('Your name (optional)').fill('Charlie')
  await charlie.getByRole('button', { name: 'Join', exact: true }).click()
  await expect(charlie.getByRole('heading', { name: 'Waiting for party approval' })).toBeVisible()

  await page.getByRole('button', { name: 'Decline' }).click()
  await bob.getByRole('button', { name: 'Decline' }).click()
  await expect(charlie).toHaveURL(/\/$/)
  await expect(page.getByText('2 watching')).toBeVisible()
  await expect(page.locator('video#videoElement')).toHaveAttribute('title', 'Fake Movie')

  await charlieContext.close()
  await bobContext.close()
})

test('guest reload restores membership and a fresh HLS stream', async ({ browser, page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Create Party', exact: true }).click()
  await expect(page).toHaveURL(/\/party\/[A-Z0-9]+$/)
  const partyUrl = page.url()
  await page.getByPlaceholder('Your name (optional)').fill('Alice')
  await page.getByRole('button', { name: 'Join', exact: true }).click()

  const guestContext = await browser.newContext()
  const guest = await guestContext.newPage()
  await guest.goto(partyUrl)
  await guest.getByPlaceholder('Your name (optional)').fill('Bob')
  await guest.getByRole('button', { name: 'Join', exact: true }).click()

  await page.getByRole('main').getByRole(
    'button', { name: 'Login to Become Host', exact: true },
  ).click()
  await page.getByPlaceholder('Emby username').fill('Alice')
  await page.getByPlaceholder('Emby password').fill('password')
  await page.getByRole('button', { name: 'Become Host', exact: true }).click()
  await page.getByText('Movies', { exact: true }).click()
  await startFakeMovie(page)
  await expect(guest.locator('video#videoElement')).toHaveAttribute('title', 'Fake Movie')

  const oldSource = await guest.locator('video#videoElement').getAttribute('src')
  const restoredHlsRequests: string[] = []
  guest.on('request', (request) => {
    if (request.url().includes('/hls/movie-1/')) restoredHlsRequests.push(request.url())
  })
  await guest.reload()

  await expect(guest.getByText('2 watching')).toBeVisible()
  const restoredVideo = guest.locator('video#videoElement')
  await expect(restoredVideo).toHaveAttribute('title', 'Fake Movie')
  await expect.poll(() => restoredVideo.getAttribute('src')).not.toBe(oldSource)
  await expect.poll(() => restoredHlsRequests).toContainEqual(
    expect.stringContaining('/hls/movie-1/master.m3u8'),
  )

  await guestContext.close()
})

test('sole participant reload preserves the party during reconnect', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Create Party', exact: true }).click()
  await expect(page).toHaveURL(/\/party\/[A-Z0-9]+$/)
  const partyUrl = page.url()
  await page.getByPlaceholder('Your name (optional)').fill('Alice')
  await page.getByRole('button', { name: 'Join', exact: true }).click()
  await expect(page.getByText('1 watching')).toBeVisible()

  await page.reload()

  await expect(page).toHaveURL(partyUrl)
  await expect(page.getByText('1 watching')).toBeVisible()
  await expect(page.getByText('Joining party…')).toBeHidden()
})

test('admin modal traps focus and Escape restores its trigger', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Create Party', exact: true }).click()
  await expect(page).toHaveURL(/\/party\/[A-Z0-9]+$/)
  await page.getByPlaceholder('Your name (optional)').fill('Alice')
  await page.getByRole('button', { name: 'Join', exact: true }).click()
  await page.getByRole('main').getByRole(
    'button', { name: 'Login to Become Host', exact: true },
  ).click()
  await page.getByPlaceholder('Emby username').fill('Alice')
  await page.getByPlaceholder('Emby password').fill('password')
  await page.getByRole('button', { name: 'Become Host', exact: true }).click()

  const trigger = page.getByRole('button', { name: 'Admin', exact: true })
  await trigger.click()
  const dialog = page.getByRole('dialog', { name: 'Admin Panel' })
  await expect(dialog).toBeFocused()
  const save = page.getByRole('button', { name: 'Save Settings' })
  await expect(save).toBeVisible()

  // The rate-limit fields became value + window pairs on this branch, backed
  // by a parser that reads what the backend actually stores. This is the only
  // place the panel is exercised against the real config, so it is where a
  // parse that silently rewrites an operator's limit shows up: '10 per 15
  // minutes' read back as '10 per minute' is a fifteen-fold tightening,
  // written on the next save.
  const chatValue = dialog.getByLabel('Chat Limit', { exact: true })
  const chatWindow = dialog.getByLabel('Chat Limit window', { exact: true })
  await expect(chatValue).toHaveValue(/^[1-9]\d*$/)
  await expect(chatWindow).toHaveValue(/^per /)

  const loginWindow = dialog.getByLabel('Admin Login Limit window', { exact: true })
  await expect(dialog.getByLabel('Admin Login Limit', { exact: true })).toHaveValue(/^[1-9]\d*$/)
  await expect(loginWindow).toHaveValue(/^per /)

  await chatWindow.selectOption('per 15 minutes')
  await expect(chatWindow).toHaveValue('per 15 minutes')

  await page.keyboard.press('Shift+Tab')
  await expect(save).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'Close admin panel' })).toBeFocused()

  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(trigger).toBeFocused()
})
