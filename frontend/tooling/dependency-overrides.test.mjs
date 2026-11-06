import assert from 'node:assert/strict'
import { execFileSync } from 'node:child_process'
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync, unlinkSync, rmdirSync } from 'node:fs'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import process from 'node:process'
import test from 'node:test'
import { glob, globSync } from 'glob'
import { parse } from 'editorconfig'

const require = createRequire(import.meta.url)

test('matchers honor explicit Windows and Linux path rules', () => {
  const { minimatch, Minimatch } = require('minimatch')
  assert(new Minimatch('src/**/*.ts', { optimizationLevel: 2 }).match('src/view.ts'))
  assert(minimatch('src\\view.ts', 'src/**/*.ts', { platform: 'win32', windowsPathsNoEscape: true }))
  assert(minimatch('src/view.ts', 'src/**/*.ts', { platform: 'linux' }))
  assert.equal(minimatch('src\\view.ts', 'src/**/*.ts', { platform: 'linux' }), false)
})

test('patched matchers work with glob, EditorConfig and the formatter CLI', async t => {
  const fixture = mkdtempSync(join(tmpdir(), 'ewp-tooling-'))
  const source = join(fixture, 'src')
  const filenames = ['view.ts', 'other.js', 'ignore.txt', 'page.html']
  mkdirSync(source)
  writeFileSync(join(fixture, '.editorconfig'), 'root = true\n[*]\nend_of_line = lf\n[*.{js,ts}]\nindent_style = space\nindent_size = 2\n')
  for (const name of filenames) writeFileSync(join(source, name), '')
  t.after(() => {
    for (const name of filenames) unlinkSync(join(source, name))
    unlinkSync(join(fixture, '.editorconfig'))
    rmdirSync(source)
    rmdirSync(fixture)
  })

  const expected = ['other.js', 'view.ts'].map(name => join('src', name))
  assert.deepEqual(globSync('src/**/*.{js,ts}', { cwd: fixture }).sort(), expected)
  assert.deepEqual((await glob('src/**/*.{js,ts}', { cwd: fixture })).sort(), expected)
  const settings = await parse(join(source, 'view.ts'))
  assert.equal(settings.indent_style, 'space')
  assert.equal(settings.indent_size, 2)
  assert.equal(settings.end_of_line, 'lf')

  writeFileSync(join(source, 'page.html'), '<section><div>hello</div></section>')
  execFileSync(process.execPath, [
    require.resolve('js-beautify/js/bin/html-beautify.js'),
    '--replace', '--indent-size', '2', '--files', 'src/**/*.html',
  ], { cwd: fixture })
  assert.equal(readFileSync(join(source, 'page.html'), 'utf8').trim(), '<section>\n  <div>hello</div>\n</section>')
})
