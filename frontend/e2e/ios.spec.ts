import { expect, test } from '@playwright/test'

test('iOS viewport supports safe areas and party controls remain usable', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')

  const viewport = await page.locator('meta[name="viewport"]').getAttribute('content')
  expect(viewport).toContain('viewport-fit=cover')
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
    await page.evaluate(() => document.documentElement.clientWidth),
  )

  const createParty = page.getByRole('button', { name: 'Create Party', exact: true })
  await expect(createParty).toHaveCSS('transition-duration', '0s')
  await createParty.tap()
  await page.getByPlaceholder('Your name (optional)').fill('iPhone Guest')
  await page.getByRole('button', { name: 'Join', exact: true }).tap()

  await expect(page.getByText('1 watching')).toBeVisible()
  await page.getByRole('button', { name: 'Chat', exact: true }).tap()
  await expect(page.getByRole('heading', { name: 'Chat' })).toBeVisible()
  await expect(page.getByTitle('Close chat')).toBeVisible()
})

test('@playback-gate iPhone WebKit selects native HLS from fake Emby', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('button', { name: 'Create Party', exact: true }).tap()
  await page.getByPlaceholder('Your name (optional)').fill('Alice')
  await page.getByRole('button', { name: 'Join', exact: true }).tap()
  await page.getByRole('main').getByRole(
    'button', { name: 'Login to Become Host', exact: true },
  ).tap()
  await page.getByPlaceholder('Emby username').fill('Alice')
  await page.getByPlaceholder('Emby password').fill('password')
  await page.getByRole('button', { name: 'Become Host', exact: true }).tap()
  await page.getByText('Movies', { exact: true }).tap()
  await page.getByText('Fake Movie', { exact: true }).tap()

  const video = page.locator('video#videoElement')
  await expect(video).toHaveAttribute('playsinline', '')
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.src)).toContain(
    '/hls/movie-1/master.m3u8',
  )

  if (process.env.EXPECT_NATIVE_HLS === '1') {
    await expect.poll(
      () => video.evaluate((element: HTMLVideoElement) => element.readyState),
      { timeout: 15_000 },
    ).toBeGreaterThanOrEqual(1)
  }

  await page.getByRole('button', { name: 'Jump/Seek' }).tap()
  const seekInput = page.getByPlaceholder('1:04:07 or 10407')
  await seekInput.fill('0:05')
  await page.getByRole('button', { name: 'Go', exact: true }).tap()
  await expect(seekInput).toBeHidden()
  if (process.env.EXPECT_NATIVE_HLS === '1') {
    await expect.poll(
      () => video.evaluate((element: HTMLVideoElement) => element.currentTime),
    ).toBeGreaterThan(4)
  }

  await page.getByRole('button', { name: 'Chat', exact: true }).tap()
  const chat = page.getByPlaceholder('Type a message...')
  await chat.fill('Hello from iPhone')
  await page.getByRole('button', { name: 'Send message' }).tap()
  await expect(page.getByText('Hello from iPhone')).toBeVisible()
  await page.getByTitle('Close chat').tap()

  const oldSource = await video.getAttribute('src')
  await page.context().setOffline(true)
  await page.evaluate(() => window.dispatchEvent(new Event('offline')))
  await expect(page.getByText('Reconnecting to party…')).toBeVisible()
  await page.context().setOffline(false)
  await page.evaluate(() => window.dispatchEvent(new Event('online')))
  await expect(page.getByText('Reconnecting to party…')).toBeHidden({ timeout: 15_000 })
  await expect.poll(() => video.getAttribute('src')).not.toBe(oldSource)
})
