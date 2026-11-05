/** Build the standalone GitHub Pages tool without starting the application. */
import { readFile, writeFile, mkdir, readdir, lstat } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import { createRequire } from 'node:module'

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const source = path.join(root, 'language-pack-builder')
const output = path.join(root, 'docs')
const require = createRequire(path.join(root, 'frontend', 'package.json'))
const { build } = require('esbuild')

const args = process.argv.slice(2)
if (args.some(argument => argument !== '--check')) {
  throw new Error('Usage: node scripts/build_language_pack_builder.mjs [--check]')
}
const check = args.includes('--check')
const bundle = await build({
  entryPoints: [path.join(source, 'app.js')],
  bundle: true,
  minify: true,
  format: 'esm',
  platform: 'browser',
  target: ['es2022'],
  write: false,
  legalComments: 'eof',
  nodePaths: [path.join(root, 'frontend', 'node_modules')],
  define: { 'process.env.NODE_ENV': '"production"' },
  logLevel: 'silent',
})
const compilerLicense = await readFile(path.join(root, 'frontend/node_modules/@intlify/message-compiler/LICENSE'))
const files = new Map([
  ['index.html', await readFile(path.join(source, 'index.html'))],
  ['styles.css', await readFile(path.join(source, 'styles.css'))],
  ['app.js', Buffer.from(bundle.outputFiles[0].contents)],
  ['catalog.json', await readFile(path.join(root, 'backend/language-catalog.json'))],
  ['brand-mark.webp', await readFile(path.join(root, 'frontend/src/assets/brand-mark.webp'))],
  ['THIRD-PARTY-NOTICES.txt', compilerLicense],
  ['.nojekyll', Buffer.alloc(0)],
])

// This directory is exclusively the Pages site. Never copy repository/runtime
// directories wholesale, and never remove files while preparing an artifact.
await mkdir(output, { recursive: true })
if (!(await lstat(output)).isDirectory()) throw new Error('docs/ must be a regular directory.')
const existing = await readdir(output)
const unexpected = existing.filter(name => !files.has(name) && name !== 'CNAME')
if (unexpected.length) throw new Error(`Unexpected files in docs/: ${unexpected.join(', ')}. EWP documentation belongs in documentations/.`)
const stale = []
for (const [name, content] of files) {
  const destination = path.join(output, name)
  const info = await lstat(destination).catch(error => {
    if (error.code === 'ENOENT') return null
    throw error
  })
  if (info && !info.isFile()) throw new Error(`Expected a regular output file: ${name}`)
  if (check) {
    const current = info ? await readFile(destination) : null
    if (!current || !current.equals(content)) stale.push(`docs/${name}`)
  } else {
    await writeFile(destination, content)
  }
}
if (stale.length) {
  console.error(`Generated Pages files are stale: ${stale.join(', ')}`)
  console.error('Run node scripts/build_language_pack_builder.mjs')
  process.exitCode = 1
} else {
  console.log(`${check ? 'Verified' : 'Built'} language-pack creator in docs/`)
}
