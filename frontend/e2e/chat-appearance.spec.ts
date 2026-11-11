import { expect, test, type Page } from '@playwright/test'

const preferenceKey = 'watchparty-chat-appearance'

async function joinParty(page: Page) {
  await page.goto('/')
  await page.getByRole('button', { name: 'Create Party', exact: true }).click()
  await page.getByPlaceholder('Your name (optional)').fill('Alice')
  await page.getByRole('button', { name: 'Join', exact: true }).click()
  await expect(page.getByText('1 watching', { exact: true })).toBeVisible()
}

function options(page: Page) {
  return page.getByRole('button', { name: 'Chat options', exact: true })
}

async function openSettings(page: Page) {
  await options(page).click()
  await page.getByRole('button', { name: 'Chat settings', exact: true }).click()
  return page.getByRole('dialog', { name: 'Chat settings', exact: true })
}

test.use({ viewport: { width: 1600, height: 900 }, locale: 'en-US' })

test('the chat hover menu offers emojis and settings with keyboard dismissal', async ({ page }) => {
  await joinParty(page)
  const trigger = options(page)
  await trigger.hover()
  const menu = page.getByRole('dialog', { name: 'Chat options', exact: true })
  await expect(menu).toBeVisible()
  await expect(menu.getByRole('button', { name: 'Chat settings', exact: true })).toBeVisible()
  await menu.getByRole('button', { name: 'Emojis', exact: true }).click()
  const emojis = page.getByRole('dialog', { name: 'Emojis', exact: true })
  await expect(emojis).toBeVisible()
  await emojis.getByRole('button', { name: '🍿', exact: true }).click()
  await expect(page.getByPlaceholder('Type a message...')).toHaveValue('🍿')
  await expect(page.locator('.emoji-panel')).toHaveCount(0)

  await trigger.focus()
  await trigger.press('Enter')
  await expect(menu).toBeVisible()
  await menu.getByRole('button', { name: 'Chat settings', exact: true }).click()
  await page.getByLabel('Font', { exact: true }).focus()
  await page.keyboard.press('Escape')
  await expect(page.locator('.emoji-panel')).toHaveCount(0)
  await expect(trigger).toBeFocused()

  await trigger.press('Enter')
  await expect(menu).toBeVisible()
  await page.getByPlaceholder('Type a message...').click()
  await expect(page.locator('.emoji-panel')).toHaveCount(0)
  await expect(page.getByPlaceholder('Type a message...')).toHaveValue('🍿')
})

test('chat fonts load locally and appearance updates survive reload and reset', async ({ page }) => {
  const fontRequests: string[] = []
  page.on('request', request => {
    if (/\.woff2(?:\?|$)/.test(request.url())) fontRequests.push(request.url())
  })
  await joinParty(page)
  const composer = page.getByPlaceholder('Type a message...')
  await composer.fill('Neon text stays readable.')
  await composer.press('Enter')
  const message = page.locator('.msg-bubble').filter({ hasText: 'Neon text stays readable.' })
  await expect(message).toBeVisible()
  const header = page.locator('.chat-header h3')
  const headerBefore = await header.evaluate(element => {
    const style = getComputedStyle(element)
    return { font: style.fontFamily, size: style.fontSize }
  })
  const videoFontBefore = await page.locator('.video-area').evaluate(element => getComputedStyle(element).fontFamily)

  const settings = await openSettings(page)
  for (const [id, family] of [
    ['rajdhani', 'EWP Rajdhani'],
    ['space-grotesk', 'EWP Space Grotesk'],
    ['oxanium', 'EWP Oxanium'],
  ]) {
    await settings.getByLabel('Font', { exact: true }).selectOption(id!)
    await expect.poll(() => message.evaluate(element => getComputedStyle(element).fontFamily)).toContain(family!)
    const loaded = await page.evaluate(async name => {
      const faces = await document.fonts.load(`16px "${name}"`, 'Watch Party ÄÖÜé')
      return faces.length > 0 && faces.every(face => face.status === 'loaded')
    }, family!)
    expect(loaded, `${family} should load from the bundled font assets`).toBe(true)
  }

  const size = settings.getByLabel('Font size', { exact: true })
  await size.focus()
  await size.press('Home')
  for (let step = 0; step < 6; step++) await size.press('ArrowRight')
  await expect(size).toHaveValue('18')
  await expect(message).toHaveCSS('font-size', '18px')
  await expect(composer).toHaveCSS('font-size', '18px')
  await expect.poll(() => page.evaluate(key => JSON.parse(localStorage.getItem(key) || 'null'), preferenceKey))
    .toEqual({ font: 'oxanium', size: 18 })
  expect(await header.evaluate(element => {
    const style = getComputedStyle(element)
    return { font: style.fontFamily, size: style.fontSize }
  })).toEqual(headerBefore)
  expect(await page.locator('.video-area').evaluate(element => getComputedStyle(element).fontFamily)).toBe(videoFontBefore)
  expect(fontRequests.length).toBeGreaterThan(0)
  expect(fontRequests.every(url => new URL(url).origin === new URL(page.url()).origin)).toBe(true)

  await page.reload()
  await expect(composer).toHaveCSS('font-size', '18px')
  await expect.poll(() => composer.evaluate(element => getComputedStyle(element).fontFamily)).toContain('EWP Oxanium')
  const restored = await openSettings(page)
  await expect(restored.getByLabel('Font', { exact: true })).toHaveValue('oxanium')
  await expect(restored.getByLabel('Font size', { exact: true })).toHaveValue('18')
  await restored.getByRole('button', { name: 'Reset appearance', exact: true }).click()
  await expect(restored.getByLabel('Font', { exact: true })).toHaveValue('default')
  await expect(restored.getByLabel('Font size', { exact: true })).toHaveValue('14')
  await expect(composer).toHaveCSS('font-size', '14px')
})

test('chat settings remain reachable by touch in the narrow-screen drawer', async ({ browser, browserName, baseURL }) => {
  // Firefox does not implement Playwright's touch context emulation; it still
  // verifies the same narrow layout using clicks. Chromium and WebKit use taps.
  const context = await browser.newContext({
    baseURL,
    viewport: { width: 390, height: 844 },
    locale: 'en-US',
    ...(browserName === 'firefox' ? {} : { hasTouch: true, isMobile: true }),
  })
  const phone = await context.newPage()
  try {
    await joinParty(phone)
    const activate = async (locator: ReturnType<Page['getByRole']>) => {
      if (browserName === 'firefox') await locator.click()
      else await locator.tap()
    }
    await activate(phone.getByRole('button', { name: 'Chat', exact: true }))
    await activate(options(phone))
    await activate(phone.getByRole('button', { name: 'Chat settings', exact: true }))
    const settings = phone.getByRole('dialog', { name: 'Chat settings', exact: true })
    await expect(settings).toBeVisible()
    const bounds = (await settings.boundingBox())!
    expect(bounds.x).toBeGreaterThanOrEqual(0)
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(390)
    expect(bounds.y).toBeGreaterThanOrEqual(0)
    expect(bounds.y + bounds.height).toBeLessThanOrEqual(844)
    await settings.getByLabel('Font', { exact: true }).selectOption('rajdhani')
    await expect(settings.getByLabel('Font', { exact: true })).toHaveValue('rajdhani')
    await activate(settings.getByRole('button', { name: 'Back', exact: true }))
    await activate(phone.getByRole('button', { name: 'Emojis', exact: true }))
    await activate(phone.getByRole('dialog', { name: 'Emojis', exact: true }).getByRole('button', { name: '🎬', exact: true }))
    await expect(phone.getByPlaceholder('Type a message...')).toHaveValue('🎬')
    expect(await phone.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  } finally {
    await context.close()
  }
})
