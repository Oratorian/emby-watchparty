import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { baseCompile } from '@intlify/message-compiler'
import LanguageSelector from '@/components/LanguageSelector.vue'
import { i18n, messages, resolveLocale, setLanguagePreference, t } from './index'

afterEach(() => {
  vi.restoreAllMocks()
  setLanguagePreference('en')
})

describe('language preferences', () => {
  it('matches regional browser languages in preference order with English fallback', () => {
    expect(resolveLocale(null, ['de-AT', 'en-GB'])).toBe('de')
    expect(resolveLocale(null, ['fr-FR', 'en-US', 'de-DE'])).toBe('en')
    expect(resolveLocale('de', ['en-US'])).toBe('de')
    expect(resolveLocale('invalid', ['fr-FR'])).toBe('en')
  })

  it('switches a mounted control immediately and saves the choice', async () => {
    setLanguagePreference('en')
    const wrapper = mount(LanguageSelector)
    expect(wrapper.text()).toContain('Language')
    await wrapper.get('select').setValue('de')
    expect(wrapper.text()).toContain('Sprache')
    expect(localStorage.getItem('watchparty-language')).toBe('de')
    expect(document.documentElement.lang).toBe('de')
    expect(document.title).toContain('Die heutige Premiere')
    wrapper.unmount()
  })

  it('returns to browser detection and removes an explicit preference', async () => {
    vi.spyOn(navigator, 'languages', 'get').mockReturnValue(['de-DE'])
    setLanguagePreference('en')
    setLanguagePreference('auto')
    await nextTick()
    expect(i18n.global.locale.value).toBe('de')
    expect(localStorage.getItem('watchparty-language')).toBeNull()
  })

  it('switches language even when browser storage is blocked', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked') })
    expect(() => setLanguagePreference('de')).not.toThrow()
    expect(t('core.language')).toBe('Sprache')
  })

  it('keeps interpolation as text and chooses singular/plural forms', () => {
    setLanguagePreference('de')
    expect(t('core.request_failed', { status: '<script>bad</script>' }))
      .toBe('Anfrage fehlgeschlagen (<script>bad</script>)')
    expect(t('core.rate_limited', { count: 1 })).toContain('1 Sekunde erneut')
    expect(t('core.rate_limited', { count: 3 })).toContain('3 Sekunden erneut')
  })
})

function flatten(tree: object, prefix = ''): Record<string, string> {
  return Object.fromEntries(Object.entries(tree).flatMap(([key, value]) => {
    const path = prefix ? `${prefix}.${key}` : key
    return typeof value === 'string' ? [[path, value]] : Object.entries(flatten(value, path))
  }))
}

describe('translation catalogs', () => {
  it('has matching English/German keys and interpolation parameters, with valid message syntax', () => {
    const en = flatten(messages.en)
    const de = flatten(messages.de)
    expect(Object.keys(de).sort()).toEqual(Object.keys(en).sort())
    for (const [key, english] of Object.entries(en)) {
      const german = de[key]!
      const parameters = (value: string) => [...new Set(value.match(/\{[a-zA-Z][\w]*\}/g) || [])].sort()
      expect(parameters(german), key).toEqual(parameters(english))
      for (const value of [english, german]) {
        const errors: string[] = []
        baseCompile(value, { onError: error => errors.push(error.message) })
        expect(errors, `${key}: ${value}`).toEqual([])
      }
    }
  })
})
