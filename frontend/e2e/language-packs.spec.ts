import { execFileSync } from 'node:child_process'
import { readFile } from 'node:fs/promises'
import path from 'node:path'
import { expect, test } from '@playwright/test'

const python = process.platform === 'win32'
  ? path.resolve('../.venv/Scripts/python.exe') : 'python'

function archive(locale: string, name: string, text: string, invalid = false): Buffer {
  return execFileSync(python, ['-c', `
import io,json,sys,zipfile
data=json.loads(sys.argv[1])
buffer=io.BytesIO()
with zipfile.ZipFile(buffer,'w',compression=zipfile.ZIP_DEFLATED) as out:
    out.writestr('manifest.json',json.dumps(data['manifest'],ensure_ascii=False))
    out.writestr('interface.json',json.dumps({'index':{'create_party':data['text']}},ensure_ascii=False))
sys.stdout.buffer.write(buffer.getvalue())
`, JSON.stringify({ manifest: { format: 1, locale, name, author: 'Browser test', version: '1.0' }, text: invalid ? '{unknown}' : text })])
}

test('an admin installs, replaces and removes a pack for an already-open viewer', async ({ page, context }, testInfo) => {
  const region = { chromium: 'XA', firefox: 'XB', webkit: 'XC' }[testInfo.project.name] || 'XD'
  const locale = `fr-${region}`
  const name = `Français ${testInfo.project.name}`
  const first = 'Créer une fête'
  const updated = 'Créer une soirée'

  await page.goto('/')
  await expect(page.getByRole('button', { name: 'Create Party', exact: true })).toBeVisible()
  const login = await context.request.post('/api/admin/login', {
    data: { username: 'Alice', password: 'password' },
  })
  expect(login.ok()).toBe(true)
  expect(await login.json()).toMatchObject({ success: true })

  const admin = await context.newPage()
  await admin.goto('/admin')
  await admin.getByRole('button', { name: 'Manage language packs', exact: true }).click()
  const downloadPromise = admin.waitForEvent('download')
  await admin.getByRole('button', { name: 'Download translation template', exact: true }).click()
  const download = await downloadPromise
  const template = await readFile((await download.path())!)
  const names = JSON.parse(execFileSync(python, ['-c',
    'import io,json,sys,zipfile; print(json.dumps(zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read())).namelist()))',
  ], { input: template, encoding: 'utf8' })) as string[]
  expect(names).toContain('manifest.json')
  expect(names).toContain('core.json')
  expect(names).toContain('languagePacks.json')

  const upload = async (buffer: Buffer) => {
    await admin.getByLabel('Language pack ZIP (maximum 1 MiB)', { exact: true })
      .setInputFiles({ name: 'community.zip', mimeType: 'application/zip', buffer })
    await admin.getByRole('button', { name: 'Install language pack', exact: true }).click()
  }
  const discover = async () => {
    await page.bringToFront()
    await page.evaluate(() => window.dispatchEvent(new Event('focus')))
  }

  try {
    await upload(archive(locale, name, first))
    await expect(admin.getByText(`${name} was installed.`, { exact: true })).toBeVisible()
    await discover()
    await expect(page.locator(`.language-selector option[value="${locale}"]`)).toHaveCount(1)
    await page.getByRole('combobox', { name: 'Language', exact: true }).selectOption(locale)
    await expect(page.getByRole('button', { name: first, exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: 'Join', exact: true })).toBeVisible()

    await upload(archive(locale, name, first, true))
    await expect(admin.locator('.language-packs [role="alert"]')).toBeVisible()
    await discover()
    await expect(page.getByRole('button', { name: first, exact: true })).toBeVisible()

    await upload(archive(locale, name, updated))
    await expect(admin.getByText(`${name} was installed.`, { exact: true })).toBeVisible()
    await discover()
    await expect(page.getByRole('button', { name: updated, exact: true })).toBeVisible()

    await admin.getByRole('button', { name: `Remove ${name}`, exact: true }).click()
    await admin.getByRole('button', { name: 'Remove language pack', exact: true }).click()
    await expect(admin.getByText(`${name} was removed.`, { exact: true })).toBeVisible()
    await discover()
    await expect(page.getByRole('button', { name: 'Create Party', exact: true })).toBeVisible()
    await expect(page.locator(`.language-selector option[value="${locale}"]`)).toHaveCount(1)
    // The saved choice stays available as a code so reinstalling can restore it.
    await expect(page.locator(`.language-selector option[value="${locale}"]`)).toHaveText(locale)
  } finally {
    await context.request.delete(`/api/admin/languages/${locale}`)
    await admin.close()
  }
})
