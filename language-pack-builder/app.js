import {
  flattenCatalog, validateMessage, validateManifest, canonicalLocale,
  buildMessages, validateImportedPack, parseJson,
} from './format.js'
import { encodeZip, decodeZip } from './zip.js'

const DRAFT_KEY = 'ewp-language-pack-creator-draft-v1'
const BACKUP_KEY = 'ewp-language-pack-creator-backup-v1'
const PAGE_SIZE = 30
const MAX_ZIP_BYTES = 1024 * 1024
const MAX_JSON_BYTES = 2 * 1024 * 1024
const FIELD_NAMES = ['locale', 'name', 'author', 'version']
const SECTION_NAMES = {
  core: 'General', interface: 'Screens and dialogs', party: 'Party room',
  library: 'Library and playback', languagePacks: 'Language pack management',
  languageRuntime: 'Language loading',
}
const $ = id => document.getElementById(id)
const fields = Object.fromEntries(FIELD_NAMES.map(name => [name, $(name)]))
let english = null
let entries = []
let entryByKey = new Map()
let translations = Object.create(null)
let manifest = { locale: '', name: '', author: '', version: '1.0' }
let touchedFields = new Set()
let errors = new Map()
let page = 0
let visibleEntries = []
let renderedRows = new Map()
let savingTimer
let searchTimer
let recoveryRaw = null
let backupNeedsSaving = false
let loaded = false
let busy = false
let importVersion = 0

function notice(message, type = '') {
  const element = $('operation-notice')
  element.textContent = message
  element.className = `notice${type ? ` ${type}` : ''}`
  element.hidden = !message
}

function defaultDraft() {
  return { kind: 'ewp-language-draft', format: 1, manifest: { ...manifest }, translations: { ...translations } }
}

function saveDraft() {
  clearTimeout(savingTimer)
  if (!loaded) return
  try {
    if (backupNeedsSaving && recoveryRaw) {
      localStorage.setItem(BACKUP_KEY, recoveryRaw)
      backupNeedsSaving = false
    }
    localStorage.setItem(DRAFT_KEY, JSON.stringify(defaultDraft()))
    $('save-status').textContent = 'Draft saved in this browser.'
    $('save-status').classList.remove('unsaved')
  } catch {
    $('save-status').textContent = 'Autosave is unavailable. Download a draft to keep your work.'
    $('save-status').classList.add('unsaved')
  }
}

function scheduleSave() {
  clearTimeout(savingTimer)
  $('save-status').textContent = 'Saving draft...'
  savingTimer = setTimeout(saveDraft, 400)
}

function preservePrevious(raw, message) {
  recoveryRaw = raw
  try {
    localStorage.setItem(BACKUP_KEY, raw)
    backupNeedsSaving = false
  } catch {
    // Do not replace the saved draft until its recovery copy is durable.
    backupNeedsSaving = true
  }
  $('recovery-message').textContent = message
  $('recovery-notice').hidden = false
}

function draftData(value, { permitUnknown = false } = {}) {
  if (!value || typeof value !== 'object' || Array.isArray(value)
    || value.kind !== 'ewp-language-draft' || value.format !== 1
    || !value.manifest || typeof value.manifest !== 'object' || Array.isArray(value.manifest)
    || !value.translations || typeof value.translations !== 'object' || Array.isArray(value.translations)) {
    throw new Error('This JSON file is not a Watch Party creator draft. Open a language pack ZIP or a draft downloaded from this page.')
  }
  const nextManifest = Object.fromEntries(FIELD_NAMES.map(name => {
    const text = value.manifest[name] ?? ''
    if (typeof text !== 'string') throw new Error('Draft details must contain text values.')
    return [name, text]
  }))
  const nextTranslations = Object.create(null)
  const unknown = []
  for (const [key, text] of Object.entries(value.translations)) {
    if (!entryByKey.has(key)) {
      unknown.push(key)
      continue
    }
    if (typeof text !== 'string') throw new Error('Draft translations must contain text values.')
    nextTranslations[key] = text
  }
  if (unknown.length && !permitUnknown) {
    throw new Error(`This draft contains ${unknown.length} message key(s) that are not in the current catalog. Your current draft has not changed.`)
  }
  return { manifest: nextManifest, translations: nextTranslations, unknown }
}

function restoreDraft() {
  let raw
  try {
    raw = localStorage.getItem(DRAFT_KEY)
    recoveryRaw = localStorage.getItem(BACKUP_KEY)
    if (recoveryRaw) {
      $('recovery-message').textContent = 'A previous draft is available to download if you need to recover it.'
      $('recovery-notice').hidden = false
    }
  } catch {
    $('save-status').textContent = 'Autosave is unavailable. Download a draft to keep your work.'
    $('save-status').classList.add('unsaved')
    return
  }
  if (!raw) return
  try {
    const restored = draftData(JSON.parse(raw), { permitUnknown: true })
    manifest = restored.manifest
    translations = restored.translations
    if (restored.unknown.length) {
      preservePrevious(raw, `The English catalog has changed. ${restored.unknown.length} saved message key(s) are no longer available. Your original draft is preserved below; matching translations have been restored.`)
    } else {
      notice('Your saved draft has been restored. You can keep editing where you left off.')
    }
    $('save-status').textContent = 'Saved draft restored from this browser.'
  } catch {
    preservePrevious(raw, 'Your saved draft could not be opened. Download the original before starting over; it has not been discarded.')
  }
}

function applyFields() {
  for (const name of FIELD_NAMES) fields[name].value = manifest[name]
}

function checkAllMessages() {
  errors = new Map()
  for (const entry of entries) {
    const value = translations[entry.key] || ''
    if (!value.trim()) continue
    const error = validateMessage(value, entry.source)
    if (error) errors.set(entry.key, error)
  }
}

function stateFor(entry) {
  if (errors.has(entry.key)) return 'error'
  return (translations[entry.key] || '').trim() ? 'translated' : 'missing'
}

function updateOverview() {
  let translated = 0
  let entered = 0
  for (const entry of entries) {
    if (!(translations[entry.key] || '').trim()) continue
    entered += 1
    if (!errors.has(entry.key)) translated += 1
  }
  $('translated-count').textContent = translated.toLocaleString()
  $('remaining-count').textContent = `${(entries.length - entered).toLocaleString()} blank`
  $('translation-progress').max = entries.length || 1
  $('translation-progress').value = translated
  $('error-count').textContent = errors.size ? `${errors.size} ${errors.size === 1 ? 'message needs' : 'messages need'} attention` : 'No errors'
  $('error-count').classList.toggle('has-errors', errors.size > 0)
  const validation = validateManifest(manifest)
  for (const name of FIELD_NAMES) {
    const error = validation.errors?.[name]
    const show = Boolean(error && (touchedFields.has(name) || fields[name].value))
    $(`${name}-error`).textContent = show ? error : ''
    $(`${name}-error`).hidden = !show
    fields[name].setAttribute('aria-invalid', show ? 'true' : 'false')
  }
  $('download-zip').disabled = busy || !validation.manifest || !translated || errors.size > 0
  if (!validation.manifest) {
    $('export-hint').textContent = 'Enter a valid language code and name to prepare your pack.'
  } else if (errors.size) {
    $('export-hint').textContent = 'Fix the messages marked Needs attention before downloading.'
  } else if (!translated) {
    $('export-hint').textContent = 'Translate at least one message. Blank messages will use English.'
  } else {
    $('export-hint').textContent = `watchparty-${validation.manifest.locale}.zip · ${translated} ${translated === 1 ? 'translation' : 'translations'}`
  }
}

function updateRow(entry) {
  const row = renderedRows.get(entry.key)
  if (!row) return
  const value = translations[entry.key] || ''
  const error = errors.get(entry.key)
  const status = stateFor(entry)
  row.element.dataset.state = status
  row.state.textContent = status === 'translated' ? 'Translated' : status === 'error' ? 'Needs attention' : 'Not translated'
  row.textarea.setAttribute('aria-invalid', error ? 'true' : 'false')
  row.error.textContent = error || ''
  row.error.hidden = !error
  row.counter.textContent = `${value.length.toLocaleString()} / 8,000`
  row.useEnglish.disabled = Boolean(value.trim())
}

function changeTranslation(entry, value) {
  if (value) translations[entry.key] = value
  else delete translations[entry.key]
  const error = value.trim() ? validateMessage(value, entry.source) : null
  if (error) errors.set(entry.key, error)
  else errors.delete(entry.key)
  updateRow(entry)
  updateOverview()
  scheduleSave()
}

function createRow(entry) {
  const index = entries.indexOf(entry)
  const id = `translation-${index}`
  const element = document.createElement('article')
  element.className = 'translation-card'
  element.dataset.key = entry.key
  const heading = document.createElement('div')
  heading.className = 'message-heading'
  const key = document.createElement('code')
  key.className = 'message-key'
  key.textContent = entry.key
  const state = document.createElement('span')
  state.className = 'message-state'
  heading.append(key, state)
  const content = document.createElement('div')
  content.className = 'message-content'
  const sourceHeading = document.createElement('div')
  sourceHeading.className = 'source-heading'
  const englishLabel = document.createElement('span')
  englishLabel.textContent = 'English source'
  const useEnglish = document.createElement('button')
  useEnglish.type = 'button'
  useEnglish.textContent = 'Use English as a starting point'
  useEnglish.title = 'Fill an empty translation with the English text, then edit it.'
  sourceHeading.append(englishLabel, useEnglish)
  const source = document.createElement('p')
  source.id = `${id}-source`
  source.className = 'english-source'
  source.textContent = entry.source
  const label = document.createElement('label')
  label.className = 'translation-label'
  label.htmlFor = id
  label.textContent = 'Your translation'
  const textarea = document.createElement('textarea')
  textarea.id = id
  textarea.rows = entry.source.length > 180 ? 5 : 3
  textarea.value = translations[entry.key] || ''
  textarea.placeholder = 'Leave blank to use English'
  textarea.setAttribute('aria-describedby', `${id}-source ${id}-error`)
  textarea.addEventListener('input', () => changeTranslation(entry, textarea.value))
  useEnglish.addEventListener('click', () => {
    if (textarea.value.trim()) return
    textarea.value = entry.source
    changeTranslation(entry, textarea.value)
    textarea.focus()
  })
  const bottom = document.createElement('div')
  bottom.className = 'message-bottom'
  const placeholders = document.createElement('div')
  placeholders.className = 'placeholder-buttons'
  for (const parameter of entry.placeholders) {
    const token = `{${parameter}}`
    const insert = document.createElement('button')
    insert.type = 'button'
    insert.textContent = token
    insert.title = `Insert ${token} at the cursor`
    insert.setAttribute('aria-label', `Insert ${token}`)
    insert.addEventListener('click', () => {
      const start = textarea.selectionStart
      const end = textarea.selectionEnd
      textarea.value = textarea.value.slice(0, start) + token + textarea.value.slice(end)
      changeTranslation(entry, textarea.value)
      textarea.focus()
      textarea.setSelectionRange(start + token.length, start + token.length)
    })
    placeholders.append(insert)
  }
  const counter = document.createElement('span')
  counter.className = 'message-counter'
  bottom.append(placeholders, counter)
  const error = document.createElement('p')
  error.id = `${id}-error`
  error.className = 'message-error'
  error.hidden = true
  content.append(sourceHeading, source, label, textarea, bottom, error)
  element.append(heading, content)
  renderedRows.set(entry.key, { element, textarea, state, error, counter, useEnglish })
  updateRow(entry)
  return element
}

function filterEntries() {
  const query = $('search').value.trim().toLocaleLowerCase()
  const namespace = $('namespace').value
  const filter = $('status-filter').value
  return entries.filter(entry => {
    if (namespace !== 'all' && entry.namespace !== namespace) return false
    const status = stateFor(entry)
    if (filter === 'missing' && status !== 'missing') return false
    if (filter === 'translated' && status !== 'translated') return false
    if (filter === 'errors' && status !== 'error') return false
    return !query || [entry.key, entry.source, translations[entry.key] || '']
      .some(value => value.toLocaleLowerCase().includes(query))
  })
}

function renderRows() {
  visibleEntries = filterEntries()
  const pages = Math.max(1, Math.ceil(visibleEntries.length / PAGE_SIZE))
  page = Math.min(page, pages - 1)
  const start = page * PAGE_SIZE
  renderedRows = new Map()
  const fragment = document.createDocumentFragment()
  for (const entry of visibleEntries.slice(start, start + PAGE_SIZE)) fragment.append(createRow(entry))
  $('translation-list').replaceChildren(fragment)
  $('empty-results').hidden = visibleEntries.length > 0
  $('results-summary').textContent = visibleEntries.length
    ? `Showing ${(start + 1).toLocaleString()}-${Math.min(start + PAGE_SIZE, visibleEntries.length).toLocaleString()} of ${visibleEntries.length.toLocaleString()} messages`
    : 'No matching messages'
  $('page-count').textContent = `Page ${page + 1} of ${pages}`
  $('previous-page').disabled = page === 0
  $('next-page').disabled = page >= pages - 1
}

function download(bytes, filename, mime) {
  const url = URL.createObjectURL(new Blob([bytes], { type: mime }))
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.append(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function exportZip() {
  const validated = validateManifest(manifest)
  checkAllMessages()
  updateOverview()
  if (!validated.manifest || errors.size) return
  try {
    const messages = buildMessages(entries, translations)
    const checked = validateImportedPack(validated.manifest, messages, english)
    const files = { 'manifest.json': `${JSON.stringify(checked.manifest, null, 2)}\n` }
    for (const [namespace, tree] of Object.entries(messages)) {
      files[`${namespace}.json`] = `${JSON.stringify(tree, null, 2)}\n`
    }
    const expanded = Object.values(files).reduce((size, text) => size + new TextEncoder().encode(text).byteLength, 0)
    if (expanded > MAX_JSON_BYTES) throw new Error('The expanded language files are larger than 2 MiB. Split your work into a smaller partial pack.')
    const zip = encodeZip(files)
    if (zip.byteLength > MAX_ZIP_BYTES) throw new Error('This ZIP is larger than EWP\'s 1 MiB upload limit. Export a smaller partial pack.')
    const filename = `watchparty-${checked.manifest.locale}.zip`
    download(zip, filename, 'application/zip')
    saveDraft()
    notice(`Downloaded ${filename}. In EWP, open Admin Panel, then Manage language packs to install it.`)
  } catch (error) {
    notice(error instanceof Error ? error.message : 'The language pack could not be created.', 'error')
  }
}

function importFinishedPack(files) {
  const allowed = new Set(['manifest.json', ...Object.keys(english).map(namespace => `${namespace}.json`)])
  if (!Object.hasOwn(files, 'manifest.json')) throw new Error('The ZIP does not contain manifest.json at its root.')
  const messages = Object.create(null)
  for (const [filename, text] of Object.entries(files)) {
    if (!allowed.has(filename)) throw new Error(`Unexpected file in the language pack: ${filename}`)
    if (filename !== 'manifest.json') messages[filename.slice(0, -5)] = parseJson(text)
  }
  return validateImportedPack(parseJson(files['manifest.json']), messages, english)
}

async function importFile(file) {
  if (!file || busy) return
  const version = ++importVersion
  busy = true
  $('open-pack').disabled = true
  updateOverview()
  notice(`Opening ${file.name}...`)
  try {
    let imported
    if (/\.zip$/i.test(file.name)) {
      if (!file.size || file.size > MAX_ZIP_BYTES) throw new Error('Choose a non-empty ZIP no larger than 1 MiB.')
      imported = importFinishedPack(await decodeZip(new Uint8Array(await file.arrayBuffer())))
    } else if (/\.json$/i.test(file.name)) {
      if (!file.size || file.size > MAX_JSON_BYTES) throw new Error('Choose a creator draft no larger than 2 MiB.')
      let text
      const bytes = await file.arrayBuffer()
      try {
        text = new TextDecoder('utf-8', { fatal: true }).decode(bytes)
      } catch {
        throw new Error('Drafts must contain valid UTF-8 JSON.')
      }
      imported = draftData(parseJson(text))
    } else {
      throw new Error('Choose a language pack ZIP or a JSON draft downloaded from this page.')
    }
    if (version !== importVersion) return
    if (Object.keys(translations).length || manifest.locale || manifest.name
      || manifest.author || manifest.version !== '1.0') {
      preservePrevious(JSON.stringify(defaultDraft(), null, 2), 'Your previous draft is available below if you want to keep a copy.')
    }
    manifest = Object.fromEntries(FIELD_NAMES.map(name => [name, imported.manifest[name] || '']))
    translations = Object.assign(Object.create(null), imported.translations)
    touchedFields = new Set()
    page = 0
    $('search').value = ''
    $('namespace').value = 'all'
    $('status-filter').value = 'all'
    applyFields()
    checkAllMessages()
    renderRows()
    saveDraft()
    notice(`Opened ${file.name}. Your translations are ready to edit.`)
  } catch (error) {
    if (version === importVersion) {
      notice(`${error instanceof Error ? error.message : 'The file could not be opened.'} Your current draft has not changed.`, 'error')
    }
  } finally {
    if (version === importVersion) {
      busy = false
      $('open-pack').disabled = false
      $('import-file').value = ''
      updateOverview()
    }
  }
}

function resetDraft() {
  importVersion += 1
  busy = false
  $('open-pack').disabled = false
  $('import-file').value = ''
  clearTimeout(savingTimer)
  manifest = { locale: '', name: '', author: '', version: '1.0' }
  translations = Object.create(null)
  touchedFields = new Set()
  errors.clear()
  recoveryRaw = null
  backupNeedsSaving = false
  try {
    localStorage.removeItem(DRAFT_KEY)
    localStorage.removeItem(BACKUP_KEY)
  } catch { /* State still clears when browser storage is unavailable. */ }
  $('recovery-notice').hidden = true
  $('reset-confirmation').hidden = true
  $('reset-draft').setAttribute('aria-expanded', 'false')
  page = 0
  $('search').value = ''
  $('namespace').value = 'all'
  $('status-filter').value = 'all'
  applyFields()
  renderRows()
  updateOverview()
  $('save-status').textContent = 'Draft cleared. Your downloaded files have not changed.'
  notice('Ready to start a new language pack.')
  fields.locale.focus()
}

async function loadCatalog() {
  $('retry-load').hidden = true
  $('load-message').textContent = 'Loading the English messages...'
  const controller = new AbortController()
  const timeout = setTimeout(() => controller.abort(), 10000)
  try {
    const response = await fetch('./catalog.json', { cache: 'no-cache', signal: controller.signal })
    if (!response.ok) throw new Error('Catalog unavailable')
    const catalog = await response.json()
    if (catalog?.format !== 1 || !catalog.messages || typeof catalog.messages !== 'object') throw new Error('Invalid catalog')
    english = catalog.messages
    entries = flattenCatalog(english)
    if (!entries.length) throw new Error('Empty catalog')
    entryByKey = new Map(entries.map(entry => [entry.key, entry]))
    const sectionFragment = document.createDocumentFragment()
    for (const namespace of [...new Set(entries.map(entry => entry.namespace))]) {
      const option = document.createElement('option')
      option.value = namespace
      option.textContent = SECTION_NAMES[namespace] || namespace
      sectionFragment.append(option)
    }
    $('namespace').append(sectionFragment)
    $('catalog-count').textContent = `${entries.length.toLocaleString()} English messages`
    restoreDraft()
    applyFields()
    checkAllMessages()
    renderRows()
    updateOverview()
    loaded = true
    $('load-state').hidden = true
    $('creator').hidden = false
  } catch {
    $('load-message').textContent = 'The English messages could not be loaded. Your saved draft has not changed.'
    $('retry-load').hidden = false
  } finally {
    clearTimeout(timeout)
  }
}

for (const name of FIELD_NAMES) {
  fields[name].addEventListener('input', () => {
    manifest[name] = fields[name].value
    touchedFields.add(name)
    updateOverview()
    scheduleSave()
  })
}
fields.locale.addEventListener('blur', () => {
  const locale = canonicalLocale(fields.locale.value.trim())
  if (!locale) return
  manifest.locale = locale
  fields.locale.value = locale
  updateOverview()
  scheduleSave()
})
$('search').addEventListener('input', () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => { page = 0; renderRows() }, 120)
})
for (const id of ['namespace', 'status-filter']) $(id).addEventListener('change', () => { page = 0; renderRows() })
$('clear-filters').addEventListener('click', () => {
  $('search').value = ''
  $('namespace').value = 'all'
  $('status-filter').value = 'all'
  page = 0
  renderRows()
})
for (const [id, direction] of [['previous-page', -1], ['next-page', 1]]) {
  $(id).addEventListener('click', () => {
    page += direction
    renderRows()
    $('translations-heading').scrollIntoView({ block: 'start' })
    $('translations-heading').focus({ preventScroll: true })
  })
}
$('download-zip').addEventListener('click', exportZip)
$('download-draft').addEventListener('click', () => {
  saveDraft()
  download(JSON.stringify(defaultDraft(), null, 2), 'watchparty-language-draft.json', 'application/json')
  notice('Draft downloaded. Open this JSON file here to continue editing later.')
})
$('open-pack').addEventListener('click', () => $('import-file').click())
$('import-file').addEventListener('change', event => { void importFile(event.target.files?.[0]) })
$('reset-draft').addEventListener('click', () => {
  const show = $('reset-confirmation').hidden
  $('reset-confirmation').hidden = !show
  $('reset-draft').setAttribute('aria-expanded', String(show))
})
$('cancel-reset').addEventListener('click', () => {
  $('reset-confirmation').hidden = true
  $('reset-draft').setAttribute('aria-expanded', 'false')
})
$('confirm-reset').addEventListener('click', resetDraft)
$('download-recovery').addEventListener('click', () => {
  if (recoveryRaw) download(recoveryRaw, 'watchparty-previous-draft.json', 'application/json')
})
$('retry-load').addEventListener('click', () => { void loadCatalog() })
window.addEventListener('beforeunload', () => { if (loaded) saveDraft() })
void loadCatalog()
