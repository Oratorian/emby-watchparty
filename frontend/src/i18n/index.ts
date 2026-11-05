import { readonly, ref, watch } from 'vue'
import { createI18n } from 'vue-i18n'
import type { Composer } from 'vue-i18n'

export type Locale = 'en' | 'de'
export type LanguagePreference = Locale | 'auto'
type Messages = { [key: string]: string | Messages }
const STORAGE_KEY = 'watchparty-language'

function loadMessages(locale: Locale): Messages {
  const modules = import.meta.glob<Messages>('../locales/*/*.json', {
    eager: true,
    import: 'default',
  })
  return Object.fromEntries(Object.entries(modules)
    .filter(([path]) => path.includes(`/locales/${locale}/`))
    .map(([path, messages]) => [path.split('/').pop()!.replace('.json', ''), messages]))
}

export const messages = { en: loadMessages('en'), de: loadMessages('de') }

export function resolveLocale(preference: string | null, languages: readonly string[]): Locale {
  if (preference === 'en' || preference === 'de') return preference
  for (const language of languages) {
    const base = language.toLowerCase().split('-')[0]
    if (base === 'en' || base === 'de') return base
  }
  return 'en'
}

function readPreference(): LanguagePreference {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    return saved === 'en' || saved === 'de' ? saved : 'auto'
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
  messages,
})

// Translation's component prop expects the general Composer type rather than
// our inferred en/de locale union. Both references use this same instance.
export const translationComposer = i18n.global as unknown as Composer

// The same reactive composer works in components, stores and API error handlers.
// Display messages are translated; protocol IDs and media metadata stay intact.
export function t(key: string, values: Record<string, string | number> | number = {}): string {
  return typeof values === 'number'
    ? i18n.global.t(key, values)
    : i18n.global.t(key, values)
}

export function setLanguagePreference(value: LanguagePreference): void {
  if (value !== 'auto' && value !== 'en' && value !== 'de') return
  preference.value = value
  i18n.global.locale.value = resolveLocale(value, browserLanguages())
  try {
    if (value === 'auto') localStorage.removeItem(STORAGE_KEY)
    else localStorage.setItem(STORAGE_KEY, value)
  } catch {
    // Language switching still works when browser storage is unavailable.
  }
}

watch(i18n.global.locale, (locale) => {
  if (typeof document !== 'undefined') {
    document.documentElement.lang = locale
    document.title = t('core.page_title')
  }
}, { immediate: true })

if (typeof window !== 'undefined') {
  window.addEventListener('languagechange', () => {
    if (preference.value === 'auto') {
      i18n.global.locale.value = resolveLocale('auto', browserLanguages())
    }
  })
  window.addEventListener('storage', (event) => {
    if (event.key !== STORAGE_KEY && event.key !== null) return
    preference.value = readPreference()
    i18n.global.locale.value = resolveLocale(preference.value, browserLanguages())
  })
}
