import assert from 'node:assert/strict'
import { after, test } from 'node:test'
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import { createRequire } from 'node:module'
import { execFileSync } from 'node:child_process'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const require = createRequire(path.join(root, 'frontend', 'package.json'))
const { buildSync } = require('esbuild')
const directory = mkdtempSync(path.join(tmpdir(), 'ewp-pack-builder-test-'))
const build = name => {
  const output = path.join(directory, `${name}.mjs`)
  buildSync({ entryPoints: [path.join(root, 'language-pack-builder', `${name}.js`)],
    bundle: true, format: 'esm', platform: 'node', outfile: output,
    nodePaths: [path.join(root, 'frontend', 'node_modules')], logLevel: 'silent' })
  return import(pathToFileURL(output).href)
}
const format = await build('format')
const zip = await build('zip')
const python = process.platform === 'win32' ? path.join(root, '.venv', 'Scripts', 'python.exe') : 'python'
after(() => {
  if (path.dirname(path.resolve(directory)) !== path.resolve(tmpdir())) throw new Error('Unexpected test directory')
  rmSync(directory, { recursive: true, force: true })
})

const english = { core: { language: 'Language', message: 'Welcome, {name}', people: '{count} person | {count} people' } }
const manifest = { format: 1, locale: 'fr', name: 'Français', author: '', version: '1.0' }

test('catalog entries preserve namespace, full keys and placeholder names', () => {
  assert.deepEqual(format.flattenCatalog(english), [
    { key: 'core.language', namespace: 'core', source: 'Language', placeholders: [] },
    { key: 'core.message', namespace: 'core', source: 'Welcome, {name}', placeholders: ['name'] },
    { key: 'core.people', namespace: 'core', source: '{count} person | {count} people', placeholders: ['count'] },
  ])
})

test('manifest normalization matches language aliases and script/region/variant casing', () => {
  assert.equal(format.canonicalLocale('IW'), 'iw')
  assert.equal(format.canonicalLocale('EN-latn-us-FONIPA-1996'), 'en-Latn-US-fonipa-1996')
  assert.equal(format.canonicalLocale('fr-12'), null)
  assert.equal(format.canonicalLocale('../fr'), null)
  assert.deepEqual(format.validateManifest({ locale: 'FR', name: ' Français ' }).manifest,
    { format: 1, locale: 'fr', name: 'Français', author: '', version: '' })
  for (const input of [
    { ...manifest, locale: 'en' }, { ...manifest, name: '' }, { ...manifest, name: 'x'.repeat(81) },
    { ...manifest, author: null }, { ...manifest, author: '<b>Author</b>' },
    { ...manifest, author: '\ud800' }, { ...manifest, version: 'bad\nvalue' },
    { ...manifest, format: true }, { ...manifest, extra: 'unexpected' },
  ]) assert.equal(format.validateManifest(input).manifest, null)
})

test('validation reports named placeholder mismatches and restricted syntax', () => {
  assert.equal(format.validateMessage('Bonjour, {name}', 'Welcome, {name}'), null)
  assert.equal(format.validateMessage('{count} personne | {count} personnes', english.core.people), null)
  assert.equal(format.validateMessage("vous{'@'}exemple.fr", 'you'), null)
  assert.equal(format.validateMessage('', 'Welcome, {name}'), null)
  assert.match(format.validateMessage('Bonjour {nom}', 'Welcome {name}'), /Keep \{name\}.*Remove \{nom\}/)
  for (const text of ['<b>Bonjour</b>', '@:core.language', 'Bad {syntax', "{'\\q'}", "{'a\nb'}", 'one | ', '\ud800', 'x'.repeat(8001)]) {
    assert.notEqual(format.validateMessage(text, 'Text'), null, text)
  }
})

test('partial messages omit blanks and validate every imported node and key', () => {
  const built = format.buildMessages(format.flattenCatalog(english), { 'core.language': 'Langue', 'core.message': '  ' })
  assert.equal(built.core.language, 'Langue')
  assert.equal(Object.hasOwn(built.core, 'message'), false)
  const imported = format.validateImportedPack(manifest, built, english)
  assert.equal(imported.translations['core.language'], 'Langue')
  for (const messages of [
    { core: { language: 'Langue', unknown: {} } },
    { core: { language: {}, message: 'Bonjour {name}' } },
    { core: { message: 'Bonjour {nom}' } }, { core: { language: '' } }, {},
    JSON.parse('{"core":{"__proto__":{},"language":"Langue"}}'),
  ]) assert.throws(() => format.validateImportedPack(manifest, messages, english))
})

test('strict JSON parsing rejects duplicate keys, reserved keys and invalid Unicode', () => {
  assert.deepEqual(format.parseJson('{"core":{"language":"Langue"}}'), { core: { language: 'Langue' } })
  for (const raw of [
    '{"a":1,"a":2}', '{"a":1,"\\u0061":2}', '{"constructor":{}}',
    '{"core":{"language":"\\ud800"}}', '{bad}',
  ]) assert.throws(() => format.parseJson(raw))
  assert.equal(format.parseJson('{"text":"literal { braces } and \\\"quotes\\\""}').text,
    'literal { braces } and "quotes"')
})

test('ZIP output round-trips Unicode and is accepted by the actual backend', async () => {
  const files = { 'manifest.json': JSON.stringify(manifest), 'core.json': JSON.stringify({ language: 'Langue', request_failed: 'Échec ({status})' }) }
  const bytes = zip.encodeZip(files)
  assert.deepEqual({ ...await zip.decodeZip(bytes) }, files)
  const archive = path.join(directory, 'accepted.zip')
  writeFileSync(archive, bytes)
  const result = execFileSync(python, ['-c',
    'import pathlib,sys; from backend.src.language_packs import LanguagePackStore; p=LanguagePackStore(pathlib.Path(sys.argv[2])).parse_archive(pathlib.Path(sys.argv[1]).read_bytes()); print(p.manifest["locale"])',
    archive, directory], { cwd: root, encoding: 'utf8' })
  assert.equal(result.trim(), 'fr')
})

test('reader imports standard Python deflate ZIPs and rejects corruption, paths and links', async () => {
  const pythonZip = (kind) => execFileSync(python, ['-c', `
import io,sys,zipfile
b=io.BytesIO()
with zipfile.ZipFile(b,'w',compression=zipfile.ZIP_DEFLATED) as z:
    i=zipfile.ZipInfo('../manifest.json' if sys.argv[1]=='path' else 'manifest.json')
    i.compress_type=zipfile.ZIP_DEFLATED
    i.external_attr=(0o120777 if sys.argv[1]=='link' else 0o100644)<<16
    z.writestr(i,'{"locale":"fr","name":"Français"}')
sys.stdout.buffer.write(b.getvalue())
`, kind])
  const bytes = pythonZip('normal')
  assert.match((await zip.decodeZip(bytes))['manifest.json'], /Français/)
  await assert.rejects(zip.decodeZip(pythonZip('path')))
  await assert.rejects(zip.decodeZip(pythonZip('link')))
  const damaged = new Uint8Array(zip.encodeZip({ 'manifest.json': 'hello' }))
  damaged[30 + 'manifest.json'.length] ^= 1
  await assert.rejects(zip.decodeZip(damaged), /checksum/)
  await assert.rejects(zip.decodeZip(new Uint8Array([1, 2, 3])))
  await assert.rejects(zip.decodeZip(new Uint8Array(1024 * 1024 + 1)))
  assert.throws(() => zip.encodeZip({ '../bad.json': '{}' }))
})

test('ZIP limits reject encrypted members, duplicates and forged decompression sizes', async () => {
  assert.throws(() => zip.encodeZip({ 'manifest.json': '{}', 'Manifest.json': '{}' }), /Duplicate/)
  assert.throws(() => zip.encodeZip(Object.fromEntries(Array.from({ length: 33 }, (_, i) => [`file${i}.json`, '{}']))))
  assert.throws(() => zip.encodeZip({ 'manifest.json': 'x'.repeat(1024 * 1024) }), /1 MiB/)
  const encrypted = new Uint8Array(zip.encodeZip({ 'manifest.json': '{}' }))
  const view = new DataView(encrypted.buffer)
  const central = view.getUint32(encrypted.length - 6, true)
  view.setUint16(6, 0x801, true)
  view.setUint16(central + 8, 0x801, true)
  await assert.rejects(zip.decodeZip(encrypted), /Encrypted/)
  const compressed = new Uint8Array(execFileSync(python, ['-c', `
import io,sys,zipfile
b=io.BytesIO()
with zipfile.ZipFile(b,'w',compression=zipfile.ZIP_DEFLATED) as z:z.writestr('core.json','x'*10000)
sys.stdout.buffer.write(b.getvalue())
`]))
  const compressedView = new DataView(compressed.buffer)
  const compressedCentral = compressedView.getUint32(compressed.length - 6, true)
  compressedView.setUint32(compressedCentral + 24, 5, true)
  await assert.rejects(zip.decodeZip(compressed), /2 MiB/)
})

test('every shipped English message can pass through the builder unchanged', () => {
  const catalog = JSON.parse(readFileSync(path.join(root, 'backend', 'language-catalog.json'), 'utf8')).messages
  for (const entry of format.flattenCatalog(catalog)) assert.equal(format.validateMessage(entry.source, entry.source), null, entry.key)
})
