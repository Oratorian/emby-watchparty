import { computed, readonly, ref, watchEffect } from 'vue'
import { createI18n } from 'vue-i18n'
import type { Composer } from 'vue-i18n'
import { withPrefix } from '@/utils/appPrefix'
import { canonicalLocale, parseLanguageCatalog, parseLanguageList } from './packs'
import type { LanguagePackSummary, Messages } from './packs'

export type Locale = string
export type LanguagePreference = string
export type { LanguagePackSummary } from './packs'
const STORAGE_KEY = 'watchparty-language'
const REQUEST_TIMEOUT_MS = 8000

function loadMessages(locale: string): Messages {
  const modules = import.meta.glob<Messages>('../locales/*/*.json', {
    eager: true,
    import: 'default',
  })
  return Object.fromEntries(Object.entries(modules)
    .filter(([path]) => path.includes(`/locales/${locale}/`))
    .map(([path, catalog]) => [path.split('/').pop()!.replace('.json', ''), catalog]))
}

export const messages = { en: loadMessages('en'), de: loadMessages('de') }
const bundledLanguages = [{ locale: 'en', name: 'English' }, { locale: 'de', name: 'Deutsch' }]
const customLanguages = ref<LanguagePackSummary[]>([])
export const availableLanguages = computed(() => {
  const options = new Map(bundledLanguages.map(language => [language.locale, { ...language }]))
  for (const language of customLanguages.value) options.set(language.locale, { ...language })
  return [...options.values()]
})

export function resolveLocale(
  preference: string | null,
  languages: readonly string[],
  available: readonly string[] = ['en', 'de'],
): Locale {
  const lookup = (language: string): string | undefined => {
    const canonical = canonicalLocale(language)
    if (!canonical) return undefined
    const parts = canonical.split('-')
    while (parts.length) {
      const match = available.find(value => value.toLowerCase() === parts.join('-').toLowerCase())
      if (match) return match
      parts.pop()
    }
    return undefined
  }
  if (preference && preference !== 'auto') return lookup(preference) || 'en'
  for (const language of languages) {
    const match = lookup(language)
    if (match) return match
  }
  return 'en'
}

function readPreference(): LanguagePreference {
  try {
    return canonicalLocale(localStorage.getItem(STORAGE_KEY)) || 'auto'
  } catch {
    return 'auto'
  }
}

function browserLanguages(): readonly string[] {
  return typeof navigator === 'undefined' ? [] : navigator.languages?.length
    ? navigator.languages : [navigator.language]
}

const preference = ref<LanguagePreference>(readPreference())
export const languagePreference = readonly(preference)
export const i18n = createI18n({
  legacy: false,
  globalInjection: false,
  locale: resolveLocale(preference.value, browserLanguages()),
  fallbackLocale: 'en',
  missingWarn: false,
  fallbackWarn: false,
  // The composer replaces locale properties in its input object. Keep the
  // bundled catalogs separate so removing an override can restore them.
  messages: { en: structuredClone(messages.en), de: structuredClone(messages.de) } as Record<string, Messages>,
})
export const translationComposer = i18n.global as unknown as Composer

// Display messages are translated; protocol IDs and media metadata stay intact.
export function t(key: string, values: Record<string, string | number> | number = {}): string {
  return typeof values === 'number' ? i18n.global.t(key, values) : i18n.global.t(key, values)
}

const listLoading = ref(false)
const selectionLoading = ref(false)
const listError = ref(false)
const selectionError = ref(false)
const listedOnce = ref(false)
export const languagePackLoading = computed(() => selectionLoading.value || (listLoading.value && !listedOnce.value))
export const languagePackError = computed(() => listError.value || selectionError.value)
const loadedPacks = new Map<string, { revision: string; messages: Messages }>()
const catalogRequests = new Map<string, Promise<Messages>>()
const controllers = new Set<AbortController>()
let refreshPending: Promise<void> | null = null
let selectionVersion = 0
let lifecycleVersion = 0

async function fetchJson(path: string, maxBytes: number): Promise<unknown> {
  const controller = new AbortController()
  controllers.add(controller)
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  try {
    const response = await fetch(withPrefix(path), {
      signal: controller.signal,
      credentials: 'same-origin',
      cache: 'no-store',
      headers: { Accept: 'application/json' },
    })
    if (!response.ok || !response.body) throw new Error('Language pack unavailable')
    const reader = response.body.getReader()
    const chunks: Uint8Array[] = []
    let length = 0
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        length += value.byteLength
        if (length > maxBytes) throw new Error('Language response too large')
        chunks.push(value)
      }
    } finally {
      await reader.cancel()
    }
    const bytes = new Uint8Array(length)
    let offset = 0
    for (const chunk of chunks) {
      bytes.set(chunk, offset)
      offset += chunk.length
    }
    return JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes)) as unknown
  } finally {
    clearTimeout(timeout)
    controllers.delete(controller)
  }
}

function selectedLocale(): string {
  return resolveLocale(preference.value, browserLanguages(), availableLanguages.value.map(item => item.locale))
}

function requestCatalog(summary: LanguagePackSummary): Promise<Messages> {
  const key = `${summary.locale}:${summary.revision}`
  const existing = catalogRequests.get(key)
  if (existing) return existing
  // The response adds locale/revision fields around the bounded stored messages.
  const request = fetchJson(`/api/languages/${encodeURIComponent(summary.locale)}`, 2 * 1024 * 1024 + 64 * 1024)
    .then(value => parseLanguageCatalog(value, summary, messages.en))
    .finally(() => catalogRequests.delete(key))
  catalogRequests.set(key, request)
  return request
}

async function applyRequestedLocale(): Promise<void> {
  const request = ++selectionVersion
  const target = selectedLocale()
  const summary = customLanguages.value.find(language => language.locale === target)
  selectionError.value = false
  selectionLoading.value = false
  if (!summary) {
    i18n.global.locale.value = target
    // Retain the requested preference for a pack that becomes available later.
    selectionError.value = preference.value !== 'auto' && target === 'en' && preference.value !== 'en'
    return
  }
  const previous = loadedPacks.get(target)
  if (previous?.revision === summary.revision) {
    i18n.global.locale.value = target
    return
  }
  i18n.global.locale.value = previous ? target : target === 'de' ? 'de' : 'en'
  selectionLoading.value = true
  try {
    const catalog = await requestCatalog(summary)
    if (selectionVersion !== request
      || customLanguages.value.find(item => item.locale === target)?.revision !== summary.revision) return
    loadedPacks.set(target, { revision: summary.revision, messages: catalog })
    i18n.global.setLocaleMessage(target, catalog)
    if (selectionVersion === request) i18n.global.locale.value = target
  } catch {
    if (selectionVersion === request) selectionError.value = true
  } finally {
    if (selectionVersion === request) selectionLoading.value = false
  }
}

export function setLanguagePreference(value: LanguagePreference): void {
  const canonical = value === 'auto' ? 'auto' : canonicalLocale(value)
  if (!canonical) return
  preference.value = canonical
  try {
    if (canonical === 'auto') localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, canonical)
  } catch {
    // Language switching still works when browser storage is unavailable.
  }
  void applyRequestedLocale()
}

/** Refresh metadata and the selected changed catalog without rebuilding or reloading. */
export function refreshLanguagePacks(force = false): Promise<void> {
  if (refreshPending) {
    if (!force) return refreshPending
    // A mutation may finish after an older discovery request started. Wait for
    // that request, then discover again rather than returning its stale list.
    const generation = lifecycleVersion
    return refreshPending.then(() => {
      if (generation === lifecycleVersion) return refreshLanguagePacks()
    })
  }
  listLoading.value = true
  const generation = lifecycleVersion
  refreshPending = (async () => {
    try {
      const languages = parseLanguageList(await fetchJson('/api/languages', 64 * 1024))
      if (generation !== lifecycleVersion) return
      const active = new Set(languages.map(language => language.locale))
      for (const locale of loadedPacks.keys()) {
        if (active.has(locale)) continue
        loadedPacks.delete(locale)
        i18n.global.setLocaleMessage(locale, locale === 'de' ? messages.de : {})
      }
      customLanguages.value = languages
      listedOnce.value = true
      listError.value = false
      await applyRequestedLocale()
    } catch {
      // Existing valid catalogs and bundled languages stay usable during outages.
      listError.value = true
    } finally {
      listLoading.value = false
    }
  })().finally(() => { refreshPending = null })
  return refreshPending
}

/** App owns the polling lifecycle; closing it releases requests, timers and listeners. */
export function startLanguagePackRefresh(): () => void {
  const refresh = () => {
    if (document.visibilityState !== 'hidden') void refreshLanguagePacks()
  }
  const languageChanged = () => {
    if (preference.value === 'auto') void applyRequestedLocale()
  }
  const storageChanged = (event: StorageEvent) => {
    if (event.key !== STORAGE_KEY && event.key !== null) return
    preference.value = readPreference()
    void applyRequestedLocale()
  }
  window.addEventListener('focus', refresh)
  window.addEventListener('languagechange', languageChanged)
  window.addEventListener('storage', storageChanged)
  document.addEventListener('visibilitychange', refresh)
  const timer = window.setInterval(refresh, 30_000)
  void refreshLanguagePacks()
  return () => {
    window.clearInterval(timer)
    window.removeEventListener('focus', refresh)
    window.removeEventListener('languagechange', languageChanged)
    window.removeEventListener('storage', storageChanged)
    document.removeEventListener('visibilitychange', refresh)
    selectionVersion += 1
    lifecycleVersion += 1
    selectionLoading.value = false
    for (const controller of controllers) controller.abort()
  }
}

watchEffect(() => {
  if (typeof document !== 'undefined') {
    document.documentElement.lang = i18n.global.locale.value
    document.title = t('core.page_title')
  }
})
