import { baseCompile } from '@intlify/message-compiler'

const FORBIDDEN_KEYS = new Set(['__proto__', 'constructor', 'prototype'])
const LOCALE_PATTERN = /^[a-z]{2,3}(?:-[a-z]{4})?(?:-(?:[a-z]{2}|\d{3}))?(?:-(?:[a-z0-9]{5,8}|\d[a-z0-9]{3})){0,2}$/i
const TOKEN_PATTERN = /\{(?:[A-Za-z][A-Za-z0-9_]*|'[^'{}]*')\}/g

function record(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const prototype = Object.getPrototypeOf(value)
  return prototype === Object.prototype || prototype === null
}

function validUnicode(value) {
  for (let index = 0; index < value.length; index++) {
    const unit = value.charCodeAt(index)
    if (unit >= 0xd800 && unit <= 0xdbff) {
      const next = value.charCodeAt(++index)
      if (!(next >= 0xdc00 && next <= 0xdfff)) return false
    } else if (unit >= 0xdc00 && unit <= 0xdfff) return false
  }
  return true
}

function parameters(message) {
  return [...new Set([...message.matchAll(/\{([A-Za-z][A-Za-z0-9_]*)\}/g)].map(match => match[1]))].sort()
}

export function canonicalLocale(value) {
  if (typeof value !== 'string' || !LOCALE_PATTERN.test(value)) return null
  return value.split('-').map((part, index) => {
    if (!index) return part.toLowerCase()
    if (/^[a-z]{4}$/i.test(part)) return part[0].toUpperCase() + part.slice(1).toLowerCase()
    if (/^[a-z]{2}$/i.test(part)) return part.toUpperCase()
    return part.toLowerCase()
  }).join('-')
}

export function flattenCatalog(messages) {
  const entries = []
  function visit(node, parts) {
    if (!record(node) || parts.length > 8) throw new Error('Invalid English catalog structure.')
    for (const [key, value] of Object.entries(node)) {
      if (!key || key.includes('.') || FORBIDDEN_KEYS.has(key)) throw new Error('Invalid English catalog key.')
      const path = [...parts, key]
      if (typeof value === 'string') {
        entries.push({ key: path.join('.'), namespace: path[0], source: value, placeholders: parameters(value) })
      } else visit(value, path)
    }
  }
  visit(messages, [])
  return entries
}

export function validateMessage(value, source) {
  if (typeof value !== 'string') return 'A translation must be text.'
  if (!value.trim()) return null
  if (!validUnicode(value)) return 'Remove the invalid Unicode character.'
  // This also stays within the web client's UTF-16 limit for supplementary characters.
  if (value.length > 8000) return 'Keep this message within 8,000 characters.'
  if (/[<>]/.test(value)) return 'Use plain text, without HTML or angle brackets.'
  for (const match of value.matchAll(TOKEN_PATTERN)) {
    if (match[0].startsWith("{'") && /[\\\x00-\x1f]/.test(match[0])) {
      return 'Quoted literals cannot contain backslashes or control characters.'
    }
  }
  if (/[{}@]/.test(value.replace(TOKEN_PATTERN, ''))) {
    return "Use named placeholders such as {name}; escape a literal at sign as {'@'}."
  }
  if (value.split('|').some(branch => !branch.trim())) return 'Every plural form must contain text.'
  const expected = parameters(source)
  const actual = parameters(value)
  const missing = expected.filter(name => !actual.includes(name))
  const extra = actual.filter(name => !expected.includes(name))
  if (missing.length || extra.length) {
    return [
      missing.length ? `Keep ${missing.map(name => `{${name}}`).join(', ')}.` : '',
      extra.length ? `Remove ${extra.map(name => `{${name}}`).join(', ')}.` : '',
    ].filter(Boolean).join(' ')
  }
  const errors = []
  try {
    baseCompile(value, { onError: error => errors.push(error.message) })
  } catch {
    return 'This message has invalid translation syntax.'
  }
  return errors.length ? 'This message has invalid translation syntax.' : null
}

export function validateManifest(value) {
  const errors = Object.create(null)
  if (!record(value)) return { manifest: null, errors: { manifest: 'Enter the language details.' } }
  if (Object.keys(value).some(key => !['format', 'locale', 'name', 'author', 'version'].includes(key))) {
    errors.manifest = 'The manifest contains an unknown field.'
  }
  if (value.format !== undefined && value.format !== 1) errors.format = 'Use language pack format 1.'
  const locale = canonicalLocale(value.locale)
  if (!locale) errors.locale = 'Use a code such as fr, pt-BR or zh-Hant.'
  else if (locale === 'en' || locale === 'auto') errors.locale = 'English is the included fallback and cannot be replaced.'
  const result = { format: 1, locale, name: '', author: '', version: '' }
  for (const [key, maximum, required] of [['name', 80, true], ['author', 100, false], ['version', 40, false]]) {
    const text = value[key] === undefined ? (required ? null : '') : value[key]
    if (typeof text !== 'string' || text.length > maximum || !validUnicode(text)) {
      errors[key] = `Use text no longer than ${maximum} characters.`
    } else if (/[<>\x00-\x1f]/.test(text)) {
      errors[key] = 'Use plain text without HTML or control characters.'
    } else if (required && !text.trim()) {
      errors[key] = 'Enter the language name, for example Français.'
    } else result[key] = text.trim()
  }
  return { manifest: Object.keys(errors).length ? null : result, errors }
}

export function buildMessages(entries, translations) {
  const result = Object.create(null)
  for (const entry of entries) {
    const value = translations instanceof Map ? translations.get(entry.key) : translations?.[entry.key]
    if (value === undefined || value === null || value === '') continue
    const error = validateMessage(value, entry.source)
    if (error) throw new Error(`${entry.key}: ${error}`)
    if (!value.trim()) continue
    const parts = entry.key.split('.')
    let node = result
    for (const key of parts.slice(0, -1)) {
      if (FORBIDDEN_KEYS.has(key)) throw new Error('Reserved translation key.')
      node[key] ??= Object.create(null)
      node = node[key]
    }
    node[parts.at(-1)] = value
  }
  return result
}

export function validateImportedPack(manifest, messages, english) {
  const checked = validateManifest(manifest)
  if (!checked.manifest || manifest.format !== 1) {
    throw new Error(Object.values(checked.errors)[0] || 'Use language pack format 1.')
  }
  const translations = Object.create(null)
  function visit(node, source, parts) {
    if (!record(node) || !record(source) || parts.length > 8) throw new Error('The pack does not follow the English catalog structure.')
    for (const [key, value] of Object.entries(node)) {
      const path = [...parts, key]
      if (FORBIDDEN_KEYS.has(key) || !Object.hasOwn(source, key)) {
        throw new Error(`Unknown translation key: ${path.join('.').slice(0, 120)}.`)
      }
      if (typeof source[key] === 'string') {
        if (typeof value !== 'string' || !value.trim()) throw new Error(`${path.join('.')}: A translated message cannot be empty.`)
        const error = validateMessage(value, source[key])
        if (error) throw new Error(`${path.join('.')}: ${error}`)
        translations[path.join('.')] = value
      } else visit(value, source[key], path)
    }
  }
  visit(messages, english, [])
  if (!Object.keys(translations).length) throw new Error('Add at least one translation before importing a pack.')
  return { manifest: checked.manifest, translations }
}

export function parseJson(text) {
  let value
  try { value = JSON.parse(text) } catch { throw new Error('Each language file must contain valid JSON.') }
  const stack = []
  const tokens = /"(?:\\.|[^"\\])*"|[{}\[\],:]/g
  for (const match of text.matchAll(tokens)) {
    const token = match[0]
    if (token === '{' || token === '[') {
      if (stack.length > 12) throw new Error('Translation nesting is too deep.')
      stack.push({ object: token === '{', key: token === '{', keys: new Set() })
    } else if (token === '}' || token === ']') stack.pop()
    else if (token === ',' && stack.at(-1)?.object) stack.at(-1).key = true
    else if (token[0] === '"') {
      const decoded = JSON.parse(token)
      if (!validUnicode(decoded)) throw new Error('Language files contain an invalid Unicode character.')
      const frame = stack.at(-1)
      if (frame?.object && frame.key) {
        if (FORBIDDEN_KEYS.has(decoded)) throw new Error('Reserved JSON keys are not allowed.')
        if (frame.keys.has(decoded)) throw new Error(`Duplicate JSON key: ${decoded.slice(0, 80)}.`)
        frame.keys.add(decoded)
        frame.key = false
      }
    }
  }
  return value
}
