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

  await page.getByText('Movies', { exact: true }).click()
  const movie = page.getByText('Fake Movie', { exact: true })
  await expect(movie).toBeVisible()
  await movie.click()
  await expect(page.locator('video#videoElement')).toHaveAttribute('title', 'Fake Movie')
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
  await page.locator('video#videoElement').evaluate((video: HTMLVideoElement) => video.play())
  await expect(guest.getByText('Alice started playback')).toBeVisible()
  await page.waitForTimeout(600)
  await page.locator('video#videoElement').evaluate((video: HTMLVideoElement) => video.pause())
  await expect(guest.getByText('Alice paused playback')).toBeVisible()

  await guestContext.close()
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
