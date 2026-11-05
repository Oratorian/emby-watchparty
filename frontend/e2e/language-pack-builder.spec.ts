import { createServer, type Server } from 'node:http'
import { readFile } from 'node:fs/promises'
import { execFileSync } from 'node:child_process'
import path from 'node:path'
import { expect, test } from '@playwright/test'

const root = path.resolve('..')
const python = process.platform === 'win32' ? path.join(root, '.venv/Scripts/python.exe') : 'python'
let server: Server
let address: string

test.beforeAll(async () => {
  const mime: Record<string, string> = {
    'index.html': 'text/html', 'app.js': 'text/javascript', 'styles.css': 'text/css',
    'catalog.json': 'application/json', 'brand-mark.webp': 'image/webp',
  }
  server = createServer(async (request, response) => {
    const name = new URL(request.url!, 'http://local').pathname.replace('/emby-watchparty/', '') || 'index.html'
    if (!mime[name]) { response.writeHead(404).end(); return }
    response.setHeader('Content-Type', mime[name])
    response.end(await readFile(path.join(root, 'docs', name)))
  })
  await new Promise<void>(resolve => server.listen(0, '127.0.0.1', resolve))
  const port = (server.address() as { port: number }).port
  address = `http://127.0.0.1:${port}/emby-watchparty/`
})

test.afterAll(async () => {
  await new Promise<void>((resolve, reject) => server.close(error => error ? reject(error) : resolve()))
})

function frenchZip(invalid = false): Buffer {
  return execFileSync(python, ['-c', `
import io,json,sys,zipfile
out=io.BytesIO()
with zipfile.ZipFile(out,'w',compression=zipfile.ZIP_DEFLATED) as archive:
 archive.writestr('manifest.json',json.dumps({'format':1,'locale':'fr','name':'Français'}))
 archive.writestr('core.json',json.dumps({'request_failed':'Erreur ({etat})'} if sys.argv[1]=='bad' else {'language':'Langue'}))
sys.stdout.buffer.write(out.getvalue())
`, invalid ? 'bad' : 'good'])
}

test('creates a validated ZIP and restores a saved translation draft', async ({ page }) => {
  await page.goto(address)
  await expect(page.locator('#creator')).toBeVisible()
  await page.locator('#locale').fill('FR')
  await page.locator('#name').fill('Français')
  await page.locator('[data-key="core.language"] textarea').fill('Langue')
  await page.locator('#search').fill('core.request_failed')
  const message = page.locator('[data-key="core.request_failed"]')
  await message.locator('textarea').fill('Erreur ({etat})')
  await expect(message.locator('.message-error')).toContainText('Keep {status}')
  await expect(page.locator('#download-zip')).toBeDisabled()
  await message.locator('textarea').fill('Erreur ({status})')
  await expect(page.locator('#download-zip')).toBeEnabled()
  await page.reload()
  await expect(page.locator('#name')).toHaveValue('Français')
  await expect(page.locator('[data-key="core.language"] textarea')).toHaveValue('Langue')
  const downloading = page.waitForEvent('download')
  await page.locator('#download-zip').click()
  const downloaded = await downloading
  expect(downloaded.suggestedFilename()).toBe('watchparty-fr.zip')
  const result = execFileSync(python, ['-c', `
import json,pathlib,sys
sys.path.insert(0,sys.argv[1])
from backend.src.language_packs import LanguagePackStore
pack=LanguagePackStore(pathlib.Path(sys.argv[1])/'unused-browser-test-directory').parse_archive(pathlib.Path(sys.argv[2]).read_bytes())
print(json.dumps(pack.payload()))
`, root, (await downloaded.path())!], { encoding: 'utf8' })
  expect(JSON.parse(result)).toMatchObject({ locale: 'fr', messages: { core: { language: 'Langue', request_failed: 'Erreur ({status})' } } })
})

test('imports compressed packs while preserving drafts on invalid input', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goto(address)
  await expect(page.locator('#creator')).toBeVisible()
  await page.locator('#author').fill('Original translator')
  await page.locator('#import-file').setInputFiles({ name: 'french.zip', mimeType: 'application/zip', buffer: frenchZip() })
  await expect(page.locator('#locale')).toHaveValue('fr')
  await expect(page.locator('#recovery-notice')).toBeVisible()
  const recovering = page.waitForEvent('download')
  await page.locator('#download-recovery').click()
  const recovered = await recovering
  expect(JSON.parse(await readFile((await recovered.path())!, 'utf8')).manifest.author).toBe('Original translator')
  await page.locator('#import-file').setInputFiles({ name: 'faulty.zip', mimeType: 'application/zip', buffer: frenchZip(true) })
  await expect(page.locator('#operation-notice')).toContainText('Your current draft has not changed')
  await expect(page.locator('#name')).toHaveValue('Français')
  const malformed = Buffer.concat([Buffer.from('{"kind":"ewp-language-draft","format":1,"manifest":{},"translations":{"core.language":"'), Buffer.from([255]), Buffer.from('"}}')])
  await page.locator('#import-file').setInputFiles({ name: 'corrupted.json', mimeType: 'application/json', buffer: malformed })
  await expect(page.locator('#operation-notice')).toContainText('valid UTF-8')
  await expect(page.locator('[data-key="core.language"] textarea')).toHaveValue('Langue')
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
  await page.locator('#reset-draft').click()
  await page.locator('#cancel-reset').click()
  await expect(page.locator('#name')).toHaveValue('Français')
  await page.locator('#reset-draft').click()
  await page.locator('#confirm-reset').click()
  await expect(page.locator('#name')).toHaveValue('')
  await expect(page.locator('#download-zip')).toBeDisabled()
})
