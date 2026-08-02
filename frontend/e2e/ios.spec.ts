import { expect, test } from '@playwright/test'

test('iOS viewport supports safe areas and party controls remain usable', async ({ page }) => {
  await page.goto('/')

  const viewport = await page.locator('meta[name="viewport"]').getAttribute('content')
  expect(viewport).toContain('viewport-fit=cover')
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
    await page.evaluate(() => document.documentElement.clientWidth),
  )

  await page.getByRole('button', { name: 'Create Party', exact: true }).tap()
  await page.getByPlaceholder('Your name (optional)').fill('iPhone Guest')
  await page.getByRole('button', { name: 'Join', exact: true }).tap()

  await expect(page.getByText('1 watching')).toBeVisible()
  await page.getByRole('button', { name: 'Chat', exact: true }).tap()
  await expect(page.getByRole('heading', { name: 'Chat' })).toBeVisible()
  await expect(page.getByTitle('Close chat')).toBeVisible()
})

test('iPhone WebKit selects native HLS from fake Emby', async ({ page }) => {
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
})
