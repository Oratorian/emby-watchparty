import { expect, test } from '@playwright/test'

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
  await page.route('**/api/auth/login', (route) => route.fulfill({
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

  await page.getByText('Movies', { exact: true }).click()
  const movie = page.getByText('Fake Movie', { exact: true })
  await expect(movie).toBeVisible()
  await movie.click()
  await expect(page.locator('video#videoElement')).toHaveAttribute('title', 'Fake Movie')
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

  await page.getByPlaceholder('Search...').fill('Large Movie 0420')
  await page.getByRole('button', { name: 'Search', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Clear', exact: true })).toBeVisible()
  await expect(page.locator('.item-card')).toHaveCount(1)
  await expect(page.getByText('Large Movie 0420', { exact: true })).toBeVisible()
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
  await page.getByText('Fake Movie', { exact: true }).click()

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
  await page.getByText('Fake Movie', { exact: true }).click()
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
  await page.getByText('Fake Movie', { exact: true }).click()
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
  await page.getByText('Fake Movie', { exact: true }).click()
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
  await page.getByText('Fake Movie', { exact: true }).click()
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

  await page.keyboard.press('Shift+Tab')
  await expect(save).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'Close admin panel' })).toBeFocused()

  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(trigger).toBeFocused()
})
