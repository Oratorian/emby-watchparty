import { expect, test, type Locator, type Page } from '@playwright/test'

const preferenceKey = 'watchparty-chat-width'

function divider(page: Page) {
  return page.getByRole('separator', { name: 'Resize chat panel', exact: true })
}

async function joinParty(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Create Party', exact: true }).click()
  await page.getByPlaceholder('Your name (optional)').fill('Alice')
  await page.getByRole('button', { name: 'Join', exact: true }).click()
  await expect(divider(page)).toBeVisible()
}

async function loginAsHost(page: Page) {
  await page.getByRole('main').getByRole('button', { name: 'Login to Become Host', exact: true }).click()
  await page.getByPlaceholder('Emby username').fill('Alice')
  await page.getByPlaceholder('Emby password').fill('password')
  await page.getByRole('button', { name: 'Become Host', exact: true }).click()
  await expect(page.locator('.library-panel')).toBeVisible()
}

async function expectLibraryFillsContent(page: Page) {
  await expect(page.locator('.video-area')).toBeHidden()
  await expect.poll(async () => {
    const library = (await page.locator('.library-panel').boundingBox())!
    const content = (await page.locator('.party-content').boundingBox())!
    const chat = (await page.locator('#party-chat-panel').boundingBox())!
    return Math.abs(library.width + chat.width - content.width)
  }).toBeLessThanOrEqual(1)
}

async function expectWidth(page: Page, width: number) {
  await expect(divider(page)).toHaveAttribute('aria-valuenow', String(width))
  await expect.poll(async () => {
    const bounds = await page.locator('#party-chat-panel').boundingBox()
    return bounds && Math.round(bounds.width)
  }).toBe(width)
}

async function drag(page: Page, handle: Locator, destinationX: number) {
  const bounds = await handle.boundingBox()
  expect(bounds).not.toBeNull()
  const x = bounds!.x + bounds!.width / 2
  const y = bounds!.y + bounds!.height / 2
  await page.mouse.move(x, y)
  await page.mouse.down()
  await page.mouse.move(destinationX, y, { steps: 8 })
  await page.mouse.up()
}

test.use({ viewport: { width: 1600, height: 900 }, locale: 'en-US' })

test('dragging resizes chat in both directions and respects its limits', async ({ page }) => {
  await joinParty(page)
  const handle = divider(page)
  await expect(handle).toHaveAttribute('aria-controls', 'party-chat-panel')
  await expect(handle).toHaveAttribute('aria-orientation', 'vertical')
  await expect(handle).toHaveAttribute('aria-valuemin', '260')
  await expect(handle).toHaveAttribute('aria-valuemax', '560')
  await expectWidth(page, 320)
  expect(await page.evaluate(key => localStorage.getItem(key), preferenceKey)).toBeNull()

  let bounds = (await handle.boundingBox())!
  await drag(page, handle, bounds.x + bounds.width / 2 - 120)
  await expectWidth(page, 440)
  bounds = (await handle.boundingBox())!
  await drag(page, handle, bounds.x + bounds.width / 2 + 80)
  await expectWidth(page, 360)

  // Move well beyond the size limits using actual captured pointer events.
  await drag(page, handle, 50)
  await expectWidth(page, 560)
  await drag(page, handle, 1580)
  await expectWidth(page, 260)
  await page.mouse.move(700, 400)
  await expectWidth(page, 260)

  await handle.dblclick()
  await expectWidth(page, 320)
})

test('keyboard resizing survives reload and temporary viewport constraints', async ({ page }) => {
  await joinParty(page)
  const handle = divider(page)
  await handle.focus()
  await handle.press('ArrowLeft')
  await expectWidth(page, 340)
  await handle.press('ArrowRight')
  await expectWidth(page, 320)
  await handle.press('Home')
  await expectWidth(page, 260)
  await handle.press('End')
  await expectWidth(page, 560)
  await handle.press('ArrowRight')
  await expectWidth(page, 540)

  await page.reload()
  await expectWidth(page, 540)
  await page.setViewportSize({ width: 1300, height: 900 })
  await expectWidth(page, 520)
  expect(await page.evaluate(key => localStorage.getItem(key), preferenceKey)).toBe('540')
  await page.setViewportSize({ width: 1600, height: 900 })
  await expectWidth(page, 540)
})

test('the library replaces the video area and keeps chat resizable', async ({ page }) => {
  await joinParty(page)
  await loginAsHost(page)
  await expectLibraryFillsContent(page)
  const handle = divider(page)
  const bounds = (await handle.boundingBox())!
  await drag(page, handle, bounds.x + bounds.width / 2 - 120)
  await expectWidth(page, 440)
  await expectLibraryFillsContent(page)
  await divider(page).press('End')
  await expectWidth(page, 560)
  await page.getByRole('button', { name: 'Hide Library', exact: true }).click()
  await expect(page.locator('.video-area')).toBeVisible()

  await page.setViewportSize({ width: 1300, height: 900 })
  await expectWidth(page, 520)
  await page.getByRole('banner').getByRole('button', { name: 'Browse Library', exact: true }).click()
  await expect(page.locator('.library-panel')).toBeVisible()
  await expectWidth(page, 520)
  await expectLibraryFillsContent(page)
  expect(await page.evaluate(key => localStorage.getItem(key), preferenceKey)).toBe('560')

  await page.setViewportSize({ width: 1280, height: 900 })
  await expect(page.locator('.video-area')).toBeHidden()
  await expect(page.locator('.chat-resize-handle')).toBeHidden()
  await page.getByRole('button', { name: 'Chat', exact: true }).click()
  const drawer = page.locator('#party-chat-panel')
  await expect(drawer).toHaveClass(/chat-mobile-open/)
  await expect.poll(async () => Math.round((await drawer.boundingBox())!.width)).toBe(360)
  await expect(page.locator('.chat-resize-handle')).toBeHidden()
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await drawer.getByRole('button', { name: 'Close', exact: true }).click()

  await page.setViewportSize({ width: 390, height: 844 })
  await expect(page.locator('.video-area')).toBeHidden()
  await expect(page.locator('.mobile-library-header')).toBeVisible()
  await expect.poll(async () => {
    const library = (await page.locator('.library-panel').boundingBox())!
    const content = (await page.locator('.party-content').boundingBox())!
    return Math.abs(library.width - content.width)
  }).toBeLessThanOrEqual(1)

  await page.setViewportSize({ width: 1600, height: 900 })
  await expect(divider(page)).toBeVisible()
  await expectWidth(page, 560)
  await expectLibraryFillsContent(page)
  await page.getByRole('button', { name: 'Hide Library', exact: true }).click()
  await expect(page.locator('.video-area')).toBeVisible()
  await expectWidth(page, 560)
})

test('browsing hides the active player without replacing its video element', async ({ page, browserName }) => {
  test.skip(browserName !== 'chromium', 'Chromium owns the fake-Emby media playback checks.')
  await joinParty(page)
  await loginAsHost(page)
  await page.getByText('Movies', { exact: true }).click()
  await page.getByText('Fake Movie', { exact: true }).click()
  await page.getByRole('button', { name: 'Set up playback', exact: true }).click()
  await page.getByRole('button', { name: 'Start watch party', exact: true }).click()
  const video = page.locator('video#videoElement')
  await expect(video).toHaveAttribute('title', 'Fake Movie')
  await expect(video).toBeVisible()
  // Keep a handle specifically to verify identity, rather than finding a
  // replacement element that merely happens to have the same selector.
  const original = (await video.elementHandle())!
  await expect(video).toHaveAttribute('src', /.+/)
  const source = await video.getAttribute('src')

  await page.getByRole('banner').getByRole('button', { name: 'Browse Library', exact: true }).click()
  await expectLibraryFillsContent(page)
  await expect(video).toBeHidden()
  expect(await original.evaluate(element => element.isConnected)).toBe(true)
  await divider(page).press('ArrowLeft')
  await expectWidth(page, 340)
  await expectLibraryFillsContent(page)
  await page.getByRole('button', { name: 'Hide Library', exact: true }).click()

  await expect(video).toBeVisible()
  expect(await original.evaluate(element => element === document.querySelector('video#videoElement'))).toBe(true)
  await expect(video).toHaveAttribute('src', source!)
  await expectWidth(page, 340)
})
