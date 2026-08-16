import { expect, test } from '@playwright/test'

test('@jellyfin-real login browse play seek reconnect stop', async ({ page }) => {
  test.setTimeout(90_000)
  let masterRequestCount = 0
  const hlsFailureStatuses: number[] = []
  page.on('request', (request) => {
    if (/\/hls\/[^/]+\/master\.m3u8/.test(request.url())) masterRequestCount += 1
  })
  page.on('response', (response) => {
    if (response.url().includes('/hls/') && response.status() >= 400) {
      hlsFailureStatuses.push(response.status())
    }
  })
  await expect((await page.request.get('/api/ready')).status()).toBe(200)
  await page.goto('/')
  await page.getByRole('button', { name: 'Create Party', exact: true }).click()
  await page.getByPlaceholder('Your name (optional)').fill('Alice')
  await page.getByRole('button', { name: 'Join', exact: true }).click()
  await page.getByRole('main').getByRole(
    'button', { name: 'Login to Become Host', exact: true },
  ).click()
  await page.getByPlaceholder('Jellyfin username').fill('Alice')
  await page.getByPlaceholder('Jellyfin password').fill('password')
  await page.getByRole('button', { name: 'Become Host', exact: true }).click()
  await page.getByText('Movies', { exact: true }).click()
  await page.getByText('Synthetic HLS', { exact: true }).click()
  await page.getByRole('button', { name: 'Play', exact: true }).click()
  await page.getByRole('button', { name: 'Start watch party', exact: true }).click()
  const video = page.locator('video#videoElement')
  await expect(video).toHaveAttribute('title', 'Synthetic HLS')
  await expect.poll(() => masterRequestCount, { timeout: 30_000 }).toBeGreaterThan(0)
  try {
    await page.waitForFunction(() => {
      const element = document.querySelector<HTMLVideoElement>('video#videoElement')
      return element && element.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA
    }, null, { timeout: 30_000 })
  } catch {
    throw new Error(
      `Video did not become playable; HLS failure statuses: ${hlsFailureStatuses.join(', ')}`,
    )
  }
  expect(hlsFailureStatuses).toEqual([])
  await video.focus()
  await video.press('Space')
  await page.getByRole('button', { name: '+10s' }).click()
  await expect.poll(() => video.evaluate((element: HTMLVideoElement) => element.currentTime))
    .toBeGreaterThan(5)
  await page.reload()
  await expect(video).toHaveAttribute('title', 'Synthetic HLS', { timeout: 20_000 })
  await page.getByRole('button', { name: 'Stop Video', exact: true }).click()
  await expect(video).toHaveCount(0)
})
