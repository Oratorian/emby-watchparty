import { flushPromises } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { canonicalLocale, parseLanguageList, validatePackMessages } from './packs'

type Runtime = typeof import('./index')
const summary = (locale = 'fr', revision = 'v1') => ({ locale, name: locale === 'fr' ? 'Français' : locale, author: '', version: '', revision })
const response = (body: unknown) => new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } })
const payload = (locale = 'fr', revision = 'v1', label = 'Langue') => ({ locale, revision, messages: { core: { language: label } } })
let runtime: Runtime | undefined

async function fresh(saved?: string) {
  vi.resetModules()
  localStorage.clear()
  if (saved) localStorage.setItem('watchparty-language', saved)
  runtime = await import('./index')
  return runtime
}

beforeEach(() => {
  delete window.APP_PREFIX
})

afterEach(() => {
  runtime?.setLanguagePreference('en')
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  vi.useRealTimers()
  delete window.APP_PREFIX
})

describe('download validation', () => {
  it('rejects unsafe or malformed messages before registration', () => {
    const english = { core: { message: 'Hello {name}', language: 'Language' } }
    for (const value of [
      { core: { unknown: 'unknown' } },
      { core: { message: 'Hallo {renamed}' } },
      { core: { message: '<b>{name}</b>' } },
      { core: { message: '@:core.message {name}' } },
      { core: { message: 'Hello {name' } },
      { core: { language: '' } },
      JSON.parse('{"core":{"__proto__":{"polluted":"yes"}}}') as unknown,
    ]) {
      expect(() => validatePackMessages(value, english)).toThrow()
    }
    expect(validatePackMessages({ core: { message: 'Bonjour {name}' } }, english))
      .toEqual({ core: { message: 'Bonjour {name}' } })
    expect({}).not.toHaveProperty('polluted')
  })

  it('rejects duplicate, noncanonical and reserved language listings', () => {
    for (const languages of [[summary(), summary()], [summary('fr-ca')], [summary('en')], [summary('../fr')]]) {
      expect(() => parseLanguageList({ languages })).toThrow()
    }
  })

  it('preserves accepted language aliases and uses matching script/region/variant casing', () => {
    expect(canonicalLocale('IW')).toBe('iw')
    expect(canonicalLocale('SH')).toBe('sh')
    expect(canonicalLocale('zh-hant-tw')).toBe('zh-Hant-TW')
    expect(canonicalLocale('de-DE-1996')).toBe('de-DE-1996')
    expect(canonicalLocale('sl-ROZAJ')).toBe('sl-rozaj')
    expect(canonicalLocale('EN-latn-us-FONIPA-1996')).toBe('en-Latn-US-fonipa-1996')
    expect(canonicalLocale('fr-12')).toBeNull()
    expect(parseLanguageList({ languages: [summary('iw'), summary('sl-rozaj')] })).toHaveLength(2)
  })
})

describe('runtime language packs', () => {
  it('loads an installed language without a build, keeping missing text in English', async () => {
    const state = await fresh()
    const fetcher = vi.fn(async (url: string) => response(url.endsWith('/languages')
      ? { languages: [summary()] } : payload()))
    vi.stubGlobal('fetch', fetcher)
    state.setLanguagePreference('fr')
    await state.refreshLanguagePacks()
    expect(state.availableLanguages.value).toContainEqual(expect.objectContaining({ locale: 'fr', name: 'Français' }))
    expect(state.i18n.global.locale.value).toBe('fr')
    expect(state.t('core.language')).toBe('Langue')
    expect(state.t('core.browser_language')).toBe('Browser language')
    expect(localStorage.getItem('watchparty-language')).toBe('fr')
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual(['/api/languages', '/api/languages/fr'])
  })

  it('retains a saved custom preference until initial discovery and catalog loading finish', async () => {
    const state = await fresh('fr')
    expect(state.languagePreference.value).toBe('fr')
    expect(state.i18n.global.locale.value).toBe('en')
    vi.stubGlobal('fetch', vi.fn(async (url: string) => response(url.endsWith('/languages')
      ? { languages: [summary()] } : payload())))
    await state.refreshLanguagePacks()
    expect(state.i18n.global.locale.value).toBe('fr')
    expect(state.t('core.language')).toBe('Langue')
  })

  it('negotiates browser region and script preferences against installed locales', async () => {
    const state = await fresh()
    expect(state.resolveLocale('auto', ['zh-Hant-TW', 'en-US'], ['en', 'de', 'zh-Hant'])).toBe('zh-Hant')
    expect(state.resolveLocale('auto', ['fr-CA', 'en-US'], ['en', 'de', 'fr'])).toBe('fr')
    expect(state.resolveLocale('de', ['fr-CA'], ['en', 'de', 'fr'])).toBe('de')
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['zh-Hant-TW', 'en-US'])
    vi.stubGlobal('fetch', vi.fn(async (url: string) => response(url.endsWith('/languages')
      ? { languages: [summary('zh-Hant')] } : payload('zh-Hant', 'v1', '語言'))))
    state.setLanguagePreference('auto')
    await state.refreshLanguagePacks()
    expect(state.i18n.global.locale.value).toBe('zh-Hant')
  })

  it('refreshes an active catalog and document title without changing locale or selection', async () => {
    const state = await fresh('fr')
    let revision = 'v1'
    vi.stubGlobal('fetch', vi.fn(async (url: string) => response(url.endsWith('/languages')
      ? { languages: [summary('fr', revision)] }
      : { locale: 'fr', revision, messages: { core: { language: revision, page_title: `EWP ${revision}` } } })))
    await state.refreshLanguagePacks()
    expect(document.title).toBe('EWP v1')
    revision = 'v2'
    await state.refreshLanguagePacks()
    expect(state.t('core.language')).toBe('v2')
    expect(document.title).toBe('EWP v2')
    expect(state.i18n.global.locale.value).toBe('fr')
    expect(state.languagePreference.value).toBe('fr')
  })

  it('restores bundled German when its custom override is removed', async () => {
    const state = await fresh('de')
    let installed = true
    vi.stubGlobal('fetch', vi.fn(async (url: string) => response(url.endsWith('/languages')
      ? { languages: installed ? [summary('de')] : [] } : payload('de', 'v1', 'Eigene Sprache'))))
    await state.refreshLanguagePacks()
    expect(state.t('core.language')).toBe('Eigene Sprache')
    installed = false
    await state.refreshLanguagePacks()
    expect(state.t('core.language')).toBe('Sprache')
    expect(state.i18n.global.locale.value).toBe('de')
    expect(state.availableLanguages.value).toContainEqual({ locale: 'de', name: 'Deutsch' })
  })

  it('falls back after deletion and honors the saved choice when the pack returns', async () => {
    const state = await fresh('fr')
    let installed = true
    vi.stubGlobal('fetch', vi.fn(async (url: string) => response(url.endsWith('/languages')
      ? { languages: installed ? [summary()] : [] } : payload())))
    await state.refreshLanguagePacks()
    installed = false
    await state.refreshLanguagePacks()
    expect(state.i18n.global.locale.value).toBe('en')
    expect(state.languagePreference.value).toBe('fr')
    installed = true
    await state.refreshLanguagePacks()
    expect(state.i18n.global.locale.value).toBe('fr')
    expect(state.languagePackError.value).toBe(false)
  })

  it('keeps a valid catalog during metadata failure and retries without a reload', async () => {
    const state = await fresh('fr')
    let offline = false
    vi.stubGlobal('fetch', vi.fn(async (url: string) => {
      if (offline) throw new Error('offline')
      return response(url.endsWith('/languages') ? { languages: [summary()] } : payload())
    }))
    await state.refreshLanguagePacks()
    offline = true
    await state.refreshLanguagePacks()
    expect(state.t('core.language')).toBe('Langue')
    expect(state.languagePackError.value).toBe(true)
    offline = false
    await state.refreshLanguagePacks()
    expect(state.languagePackError.value).toBe(false)
  })

  it('rejects a malformed replacement and preserves the previously working catalog', async () => {
    const state = await fresh('fr')
    let revision = 'v1'
    vi.stubGlobal('fetch', vi.fn(async (url: string) => response(url.endsWith('/languages')
      ? { languages: [summary('fr', revision)] }
      : payload('fr', revision, revision === 'v1' ? 'Langue' : '@:core.language'))))
    await state.refreshLanguagePacks()
    revision = 'v2'
    await state.refreshLanguagePacks()
    expect(state.t('core.language')).toBe('Langue')
    expect(state.languagePackError.value).toBe(true)
  })

  it('does not let a delayed catalog undo a newer viewer language choice', async () => {
    const state = await fresh('en')
    let finish!: (value: Response) => void
    vi.stubGlobal('fetch', vi.fn((url: string) => url.endsWith('/languages')
      ? Promise.resolve(response({ languages: [summary()] }))
      : new Promise<Response>(resolve => { finish = resolve })))
    await state.refreshLanguagePacks()
    state.setLanguagePreference('fr')
    state.setLanguagePreference('de')
    finish(response(payload()))
    await flushPromises()
    expect(state.i18n.global.locale.value).toBe('de')
    expect(state.t('core.language')).toBe('Sprache')
    expect(state.languagePackLoading.value).toBe(false)
  })

  it('discards an old revision that arrives after its replacement', async () => {
    const state = await fresh('en')
    let revision = 'v1'
    let finishOld!: (value: Response) => void
    vi.stubGlobal('fetch', vi.fn((url: string) => {
      if (url.endsWith('/languages')) return Promise.resolve(response({ languages: [summary('fr', revision)] }))
      if (revision === 'v1') return new Promise<Response>(resolve => { finishOld = resolve })
      return Promise.resolve(response(payload('fr', 'v2', 'Nouvelle langue')))
    }))
    await state.refreshLanguagePacks()
    state.setLanguagePreference('fr')
    revision = 'v2'
    await state.refreshLanguagePacks()
    finishOld(response(payload('fr', 'v1', 'Old language')))
    await flushPromises()
    expect(state.t('core.language')).toBe('Nouvelle langue')
  })

  it('deduplicates simultaneous discovery and stops polling/listeners on disposal', async () => {
    vi.useFakeTimers()
    const state = await fresh('en')
    const fetcher = vi.fn(async () => response({ languages: [] }))
    vi.stubGlobal('fetch', fetcher)
    const stop = state.startLanguagePackRefresh()
    const first = state.refreshLanguagePacks()
    expect(state.refreshLanguagePacks()).toBe(first)
    await first
    expect(fetcher).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(30_000)
    expect(fetcher).toHaveBeenCalledTimes(2)
    stop()
    window.dispatchEvent(new Event('focus'))
    await vi.advanceTimersByTimeAsync(60_000)
    expect(fetcher).toHaveBeenCalledTimes(2)
  })

  it('honors APP_PREFIX for both discovery and catalog requests', async () => {
    window.APP_PREFIX = '/watchparty'
    const state = await fresh('fr')
    const fetcher = vi.fn(async (url: string) => response(url.endsWith('/languages')
      ? { languages: [summary()] } : payload()))
    vi.stubGlobal('fetch', fetcher)
    await state.refreshLanguagePacks()
    expect(fetcher.mock.calls.map(([url]) => url)).toEqual(['/watchparty/api/languages', '/watchparty/api/languages/fr'])
  })

  it('forces fresh discovery after an older pre-mutation list resolves', async () => {
    const state = await fresh('fr')
    let finishOld!: (value: Response) => void
    let lists = 0
    const fetcher = vi.fn((url: string) => {
      if (url.endsWith('/languages')) {
        if (++lists === 1) return new Promise<Response>(resolve => { finishOld = resolve })
        return Promise.resolve(response({ languages: [summary()] }))
      }
      return Promise.resolve(response(payload()))
    })
    vi.stubGlobal('fetch', fetcher)
    const old = state.refreshLanguagePacks()
    const afterMutation = state.refreshLanguagePacks(true)
    finishOld(response({ languages: [] }))
    await old
    await afterMutation
    expect(lists).toBe(2)
    expect(state.availableLanguages.value).toContainEqual(expect.objectContaining({ locale: 'fr' }))
    expect(state.i18n.global.locale.value).toBe('fr')
    expect(state.t('core.language')).toBe('Langue')
  })

  it('allows bounded response-envelope overhead for a valid near-limit catalog', async () => {
    const state = await fresh('fr')
    const body = payload()
    // JSON whitespace is included in the transport bound, but is not a message.
    const padded = JSON.stringify(body) + ' '.repeat(2 * 1024 * 1024)
    vi.stubGlobal('fetch', vi.fn(async (url: string) => url.endsWith('/languages')
      ? response({ languages: [summary()] }) : new Response(padded)))
    await state.refreshLanguagePacks()
    expect(state.t('core.language')).toBe('Langue')
    expect(state.languagePackError.value).toBe(false)
  })
})
