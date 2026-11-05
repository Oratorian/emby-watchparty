import { createServer, type Server } from 'node:http'
import { readFile } from 'node:fs/promises'
import { createHash } from 'node:crypto'
import { createRequire } from 'node:module'
import path from 'node:path'
import { expect, test, type Page, type Route } from '@playwright/test'

const root = path.resolve('..')
const require = createRequire(path.join(root, 'frontend/package.json'))
const { buildSync } = require('esbuild')
const catalog = JSON.stringify({ format: 1, messages: { core: { language: 'Language', request_failed: 'Failed ({status})' } } })
const revision = createHash('sha256').update(catalog).digest('hex')
const endpoint = 'https://relay.test/v1/submissions'
const receipt = '7f032935-6ea6-4a45-b585-fdb29d815710'
const cors = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Methods': 'GET,POST,OPTIONS', 'Access-Control-Allow-Headers': '*' }
let server: Server
let address: string

test.beforeAll(async () => {
  const bundle = buildSync({
    entryPoints: [path.join(root, 'language-pack-builder/app.js')], bundle: true,
    format: 'esm', platform: 'browser', target: 'es2022', write: false,
    nodePaths: [path.join(root, 'frontend/node_modules')],
    define: { 'process.env.NODE_ENV': '"production"' }, logLevel: 'silent',
  }).outputFiles[0].contents
  const files: Record<string, { type: string; body: Buffer | Uint8Array }> = {
    'index.html': { type: 'text/html', body: await readFile(path.join(root, 'language-pack-builder/index.html')) },
    'styles.css': { type: 'text/css', body: await readFile(path.join(root, 'language-pack-builder/styles.css')) },
    'brand-mark.webp': { type: 'image/webp', body: await readFile(path.join(root, 'frontend/src/assets/brand-mark.webp')) },
    'app.js': { type: 'text/javascript', body: bundle },
  }
  server = createServer((request, response) => {
    const name = new URL(request.url!, 'http://local').pathname.replace('/emby-watchparty/', '') || 'index.html'
    const file = files[name]
    if (!file) { response.writeHead(404).end(); return }
    response.setHeader('Content-Type', file.type)
    response.end(file.body)
  })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  address = `http://127.0.0.1:${(server.address() as { port: number }).port}/emby-watchparty/`
})

test.afterAll(async () => {
  await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()))
})

function serviceConfig(overrides: Record<string, unknown> = {}) {
  return { require_complete: true, max_zip_bytes: 1048576, catalog_revision: revision, total_messages: 2, turnstile_site_key: null, ...overrides }
}

async function prepare(page: Page, config: Record<string, unknown> = serviceConfig()) {
  await page.route('**/catalog.json', route => route.fulfill({ contentType: 'application/json', body: catalog }))
  await page.route('**/relay-config.json', route => route.fulfill({ json: { endpoint } }))
  await page.route('https://relay.test/v1/config', route => route.fulfill({ headers: cors, json: config }))
  await page.goto(address)
  await expect(page.locator('#creator')).toBeVisible()
  await expect(page.locator('#discord-submission')).toBeVisible()
  await page.locator('#locale').fill('fr')
  await page.locator('#name').fill('Français')
}

async function complete(page: Page) {
  await page.locator('[data-key="core.language"] textarea').fill('Langue')
  await page.locator('[data-key="core.request_failed"] textarea').fill('Échec ({status})')
}

async function submission(route: Route) {
  const request = route.request()
  const body = await new Request(request.url(), {
    method: 'POST', headers: { 'Content-Type': (await request.headerValue('content-type'))! },
    body: request.postDataBuffer()!,
  }).formData()
  const file = body.get('file') as File
  return {
    id: body.get('submission_id'), catalog: body.get('catalog_revision'), token: body.get('turnstile_token'),
    filename: file.name, type: file.type, size: file.size,
  }
}

function accepted(duplicate = false) {
  return { status: 'sent', receipt, locale: 'fr', message_count: 2, duplicate }
}

test('requires full valid coverage and remembers a successful receipt', async ({ page }) => {
  const requests: Awaited<ReturnType<typeof submission>>[] = []
  const challengeRequests: string[] = []
  page.on('request', request => { if (request.url().includes('challenges.cloudflare.com')) challengeRequests.push(request.url()) })
  await page.route(endpoint, async route => {
    requests.push(await submission(route))
    await route.fulfill({ status: 201, headers: cors, json: accepted() })
  })
  await prepare(page)
  await page.locator('[data-key="core.language"] textarea').fill('Langue')
  await expect(page.locator('#submit-discord')).toBeDisabled()
  await expect(page.locator('#download-zip')).toBeEnabled()
  await page.locator('[data-key="core.request_failed"] textarea').fill('Échec ({etat})')
  await expect(page.locator('#submit-discord')).toBeDisabled()
  await page.locator('[data-key="core.request_failed"] textarea').fill('Échec ({status})')
  await expect(page.locator('#submit-discord')).toBeEnabled()
  await page.locator('#submit-discord').click()
  await expect(page.locator('#submission-status')).toContainText(receipt)
  await expect(page.locator('#submit-discord')).toBeDisabled()
  expect(requests).toHaveLength(1)
  expect(requests[0]).toMatchObject({ catalog: revision, filename: 'watchparty-fr.zip', type: 'application/zip', token: null })
  expect(requests[0]?.size).toBeGreaterThan(100)
  expect(requests[0]?.id).toMatch(/^[a-f0-9-]{36}$/)
  await page.reload()
  await expect(page.locator('#submission-status')).toContainText(receipt)
  await expect(page.locator('#submit-discord')).toBeDisabled()
  expect(requests).toHaveLength(1)
  expect(challengeRequests).toEqual([])
})

test('retries an unconfirmed request with the same ID after reload', async ({ page }) => {
  const ids: (FormDataEntryValue | null)[] = []
  await page.route(endpoint, async route => {
    ids.push((await submission(route)).id)
    if (ids.length === 1) await route.abort('failed')
    else await route.fulfill({ status: 200, headers: cors, json: accepted(true) })
  })
  await prepare(page)
  await complete(page)
  await expect(page.locator('#submit-discord')).toBeEnabled()
  await page.locator('#submit-discord').click()
  await expect(page.locator('#submission-status')).toContainText('Delivery could not be confirmed')
  await page.reload()
  await expect(page.locator('#submit-discord')).toBeEnabled()
  await page.locator('#submit-discord').click()
  await expect(page.locator('#submission-status')).toContainText('already received')
  expect(ids).toHaveLength(2)
  expect(ids[1]).toBe(ids[0])
  await expect(page.locator('[data-key="core.language"] textarea')).toHaveValue('Langue')
})

test('an unchanged language-code blur does not swallow the first submit click', async ({ page }) => {
  let requests = 0
  await page.route(endpoint, async route => {
    requests += 1
    await route.fulfill({ status: 201, headers: cors, json: accepted() })
  })
  await prepare(page)
  await complete(page)
  await expect(page.locator('#submit-discord')).toBeEnabled()
  await page.locator('#locale').focus()
  await page.locator('#submit-discord').click()
  await expect(page.locator('#submission-status')).toContainText(receipt)
  expect(requests).toBe(1)
})

test('a queued search cannot create editable rows while a submission is in flight', async ({ page }) => {
  let release!: () => void
  let started!: () => void
  const pending = new Promise<void>(resolve => { release = resolve })
  const requested = new Promise<void>(resolve => { started = resolve })
  await page.route(endpoint, async route => {
    started()
    await pending
    await route.fulfill({ status: 201, headers: cors, json: accepted() })
  })
  await prepare(page)
  await complete(page)
  await expect(page.locator('#submit-discord')).toBeEnabled()
  await page.evaluate(() => {
    const search = document.getElementById('search') as HTMLInputElement
    search.value = 'core.language'
    search.dispatchEvent(new Event('input', { bubbles: true }))
    document.getElementById('submit-discord')!.click()
  })
  await requested
  // The original search debounce is 120ms; give it time to expose a late render.
  await page.waitForTimeout(200)
  expect(await page.locator('#creator').evaluate(element =>
    [...element.querySelectorAll<HTMLInputElement>('input,textarea,select,button')]
      .filter(control => !control.disabled).map(control => control.id),
  )).toEqual([])
  await page.evaluate(() => {
    const translation = document.querySelector<HTMLTextAreaElement>('[data-key="core.language"] textarea')!
    translation.value = 'Changed during delivery'
    translation.dispatchEvent(new Event('input', { bubbles: true }))
    const name = document.getElementById('name') as HTMLInputElement
    name.value = 'Changed pack name'
    name.dispatchEvent(new Event('input', { bubbles: true }))
  })
  await expect(page.locator('[data-key="core.language"] textarea')).toHaveValue('Langue')
  await expect(page.locator('#name')).toHaveValue('Français')
  release()
  await expect(page.locator('#submission-status')).toContainText(receipt)
  await expect(page.locator('#translation-list article')).toHaveCount(1)
  await expect(page.locator('#submit-discord')).toBeDisabled()
})

test('keeps edits after rejection and uses a new ID for a changed pack', async ({ page }) => {
  const ids: (FormDataEntryValue | null)[] = []
  await page.route(endpoint, async route => {
    ids.push((await submission(route)).id)
    await route.fulfill({ status: 400, headers: cors, json: { code: 'invalid_pack', detail: '<b>Example rejection</b>' } })
  })
  await prepare(page)
  await complete(page)
  await expect(page.locator('#submit-discord')).toBeEnabled()
  await page.locator('#submit-discord').click()
  await expect(page.locator('#submission-status')).toHaveText('<b>Example rejection</b>')
  expect(await page.locator('#submission-status b').count()).toBe(0)
  await expect(page.locator('[data-key="core.language"] textarea')).toHaveValue('Langue')
  await page.locator('#author').fill('Updated translator')
  await expect(page.locator('#submit-discord')).toBeEnabled()
  await page.locator('#submit-discord').click()
  await expect.poll(() => ids.length).toBe(2)
  expect(ids[1]).not.toBe(ids[0])
})

test('catalog mismatch blocks submission without blocking ZIP downloads', async ({ page }) => {
  await prepare(page, serviceConfig({ catalog_revision: '0'.repeat(64) }))
  await complete(page)
  await expect(page.locator('#submission-status')).toContainText('different English messages')
  await expect(page.locator('#submit-discord')).toBeDisabled()
  await expect(page.locator('#download-zip')).toBeEnabled()
  await expect(page.locator('#retry-relay')).toBeVisible()
})

for (const code of ['delivery_pending', 'delivery_uncertain']) {
  test(`${code} can recheck an operator-resolved delivery with the same reference`, async ({ page }) => {
    const ids: (FormDataEntryValue | null)[] = []
    let resolved = false
    await page.route(endpoint, async route => {
      ids.push((await submission(route)).id)
      await route.fulfill(resolved
        ? { status: 200, headers: cors, json: accepted(true) }
        : { status: 409, headers: cors, json: { code, detail: 'Check with the EWP team.', receipt } })
    })
    await prepare(page)
    await complete(page)
    await expect(page.locator('#submit-discord')).toBeEnabled()
    await page.locator('#submit-discord').click()
    await expect(page.locator('#submission-status')).toContainText(receipt)
    await expect(page.locator('#submit-discord')).toBeDisabled()
    await page.reload()
    await expect(page.locator('#submission-status')).toContainText(receipt)
    await expect(page.locator('#submit-discord')).toBeDisabled()
    expect(ids).toHaveLength(1)
    await expect(page.locator('#retry-checked-submission')).toBeEnabled()
    await page.locator('#retry-checked-submission').click()
    await expect.poll(() => ids.length).toBe(2)
    await expect(page.locator('#submit-discord')).toBeDisabled()
    resolved = true
    await expect(page.locator('#retry-checked-submission')).toBeEnabled()
    await page.locator('#retry-checked-submission').click()
    await expect(page.locator('#submission-status')).toContainText('already received')
    expect(ids).toHaveLength(3)
    expect(new Set(ids).size).toBe(1)
    await expect(page.locator('#retry-checked-submission')).toBeHidden()
  })
}

test('rate limiting waits for Retry-After and never sends automatically', async ({ page }) => {
  let sends = 0
  await page.route(endpoint, async route => {
    sends += 1
    await route.fulfill({ status: 429, headers: { ...cors, 'Retry-After': '2' }, json: { code: 'rate_limited', detail: 'Try again shortly.', retry_after: 2 } })
  })
  await prepare(page)
  await complete(page)
  await expect(page.locator('#submit-discord')).toBeEnabled()
  await page.locator('#submit-discord').click()
  await expect(page.locator('#submit-discord')).toContainText('Retry in')
  await expect(page.locator('#submit-discord')).toBeDisabled()
  await expect(page.locator('#submit-discord')).toBeEnabled({ timeout: 5000 })
  expect(sends).toBe(1)
})

test('optional verification requires a fresh token for an explicitly checked retry', async ({ page }) => {
  const submitted: Awaited<ReturnType<typeof submission>>[] = []
  await page.route('https://challenges.cloudflare.com/turnstile/v0/api.js?render=explicit', route => route.fulfill({
    contentType: 'text/javascript', body: `window.turnstile = {
      render: (element, options) => { element.textContent = 'Verification check'; window.challengeOptions = options; return 'widget'; },
      reset: () => { window.challengeReset = (window.challengeReset || 0) + 1; }, remove: () => {}
    }`,
  }))
  await page.route(endpoint, async route => {
    submitted.push(await submission(route))
    await route.fulfill(submitted.length === 1
      ? { status: 409, headers: cors, json: { code: 'delivery_uncertain', detail: 'Check with the EWP team.', receipt } }
      : { status: 201, headers: cors, json: accepted() })
  })
  await prepare(page, serviceConfig({ turnstile_site_key: 'public-test-key' }))
  await complete(page)
  await expect(page.locator('#submission-challenge')).toBeVisible()
  await expect(page.locator('#submit-discord')).toBeDisabled()
  await page.evaluate(() => (window as unknown as { challengeOptions: { callback: (value: string) => void } }).challengeOptions.callback('first-token'))
  await expect(page.locator('#submit-discord')).toBeEnabled()
  await page.evaluate(() => (window as unknown as { challengeOptions: { 'expired-callback': () => void } }).challengeOptions['expired-callback']())
  await expect(page.locator('#submit-discord')).toBeDisabled()
  await page.evaluate(() => (window as unknown as { challengeOptions: { callback: (value: string) => void } }).challengeOptions.callback('fresh-token'))
  await expect(page.locator('#submit-discord')).toBeEnabled()
  await page.locator('#submit-discord').click()
  await expect(page.locator('#submission-status')).toContainText(receipt)
  await expect(page.locator('#retry-checked-submission')).toBeDisabled()
  expect(submitted[0]?.token).toBe('fresh-token')
  await page.evaluate(() => (window as unknown as { challengeOptions: { callback: (value: string) => void } }).challengeOptions.callback('retry-token'))
  await expect(page.locator('#retry-checked-submission')).toBeEnabled()
  await page.locator('#retry-checked-submission').click()
  await expect(page.locator('#submission-status')).toContainText('Your pack was received')
  expect(submitted).toHaveLength(2)
  expect(submitted[1]?.id).toBe(submitted[0]?.id)
  expect(submitted[1]?.token).toBe('retry-token')
  expect(await page.evaluate(() => (window as unknown as { challengeReset: number }).challengeReset)).toBe(2)
})
