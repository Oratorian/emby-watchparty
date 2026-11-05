import { baseCompile } from '@intlify/message-compiler'

export type Messages = { [key: string]: string | Messages }
export interface LanguagePackSummary {
  locale: string
  name: string
  author: string
  version: string
  revision: string
}

const FORBIDDEN_KEYS = new Set(['__proto__', 'constructor', 'prototype'])
const MAX_MESSAGE_LENGTH = 8192
const LOCALE_PATTERN = /^[a-z]{2,3}(?:-[a-z]{4})?(?:-(?:[a-z]{2}|\d{3}))?(?:-(?:[a-z0-9]{5,8}|\d[a-z0-9]{3})){0,2}$/i

export function canonicalLocale(value: unknown): string | null {
  if (typeof value !== 'string' || !LOCALE_PATTERN.test(value)) return null
  // Match the backend's identity rules. Intl canonicalization rewrites legacy
  // language aliases, which would otherwise reject accepted packs such as iw.
  return value.split('-').map((part, index) => {
    if (!index) return part.toLowerCase()
    if (/^[a-z]{4}$/i.test(part)) return part[0]!.toUpperCase() + part.slice(1).toLowerCase()
    if (/^[a-z]{2}$/i.test(part)) return part.toUpperCase()
    return part.toLowerCase()
  }).join('-')
}

function isRecord(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return false
  const prototype = Object.getPrototypeOf(value)
  return prototype === Object.prototype || prototype === null
}

function metadata(value: unknown, max: number, required = false): string {
  if (value === undefined && !required) return ''
  if (typeof value !== 'string' || value.length > max || /[<>]/.test(value)
    || [...value].some(character => character.charCodeAt(0) < 32)
    || (required && !value.trim())) throw new Error('Invalid language pack metadata')
  return value
}

export function parseLanguageList(value: unknown): LanguagePackSummary[] {
  if (!isRecord(value) || !Array.isArray(value.languages) || value.languages.length > 64) {
    throw new Error('Invalid language list')
  }
  const seen = new Set<string>()
  return value.languages.map((entry) => {
    if (!isRecord(entry)) throw new Error('Invalid language pack metadata')
    const locale = canonicalLocale(entry.locale)
    if (!locale || locale !== entry.locale || locale === 'en' || seen.has(locale)) {
      throw new Error('Invalid language pack locale')
    }
    seen.add(locale)
    const revision = metadata(entry.revision, 128, true)
    if (!/^[a-zA-Z0-9._-]+$/.test(revision)) throw new Error('Invalid language pack revision')
    return {
      locale,
      name: metadata(entry.name, 80, true),
      author: metadata(entry.author, 100),
      version: metadata(entry.version, 40),
      revision,
    }
  })
}

function parameters(value: string): string {
  return [...new Set(value.match(/\{[a-zA-Z][\w]*\}/g) || [])].sort().join(',')
}

export function validatePackMessages(value: unknown, english: Messages): Messages {
  let count = 0
  const visit = (node: unknown, source: Messages, depth: number): Messages => {
    if (!isRecord(node) || depth > 10) throw new Error('Invalid language messages')
    const output: Messages = Object.create(null) as Messages
    for (const [key, message] of Object.entries(node)) {
      if (FORBIDDEN_KEYS.has(key) || !Object.hasOwn(source, key)) {
        throw new Error('Unknown language message key')
      }
      const original = source[key]
      if (typeof original !== 'string') {
        if (!original) throw new Error('Unknown language message key')
        output[key] = visit(message, original, depth + 1)
        continue
      }
      if (++count > 10000 || typeof message !== 'string' || !message.trim()
        || message.length > MAX_MESSAGE_LENGTH || /[<>]/.test(message)
        || /@(?::|\.)/.test(message.replace(/\{'[^'{}]*'\}/g, ''))
        || parameters(message) !== parameters(original)) {
        throw new Error('Invalid language message')
      }
      const errors: string[] = []
      baseCompile(message, { onError: error => errors.push(error.message) })
      if (errors.length) throw new Error('Invalid language message syntax')
      output[key] = message
    }
    return output
  }
  const result = visit(value, english, 0)
  if (!count) throw new Error('Language pack has no messages')
  return result
}

export function parseLanguageCatalog(
  value: unknown,
  expected: LanguagePackSummary,
  english: Messages,
): Messages {
  if (!isRecord(value) || value.locale !== expected.locale || value.revision !== expected.revision) {
    throw new Error('Language pack changed while loading')
  }
  return validatePackMessages(value.messages, english)
}
