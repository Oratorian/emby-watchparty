import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, type LanguagePackSummary } from '@/api/client'
import { i18n } from '@/i18n'
import LanguagePacks from './LanguagePacks.vue'

const { refresh, runtime } = vi.hoisted(() => ({
  refresh: vi.fn(),
  runtime: { setError: (_value: boolean) => {} },
}))
vi.mock('@/i18n', async importOriginal => {
  const { ref } = await import('vue')
  const languagePackError = ref(false)
  runtime.setError = value => { languagePackError.value = value }
  return {
    ...await importOriginal<typeof import('@/i18n')>(),
    refreshLanguagePacks: refresh,
    languagePackError,
  }
})

const FRENCH: LanguagePackSummary = {
  locale: 'fr', name: 'Français', author: 'Community translator', version: '1.0', revision: 'one',
}
let wrapper: VueWrapper | undefined

beforeEach(() => {
  i18n.global.locale.value = 'en'
  runtime.setError(false)
  refresh.mockResolvedValue(undefined)
  vi.spyOn(api, 'languagePacks').mockResolvedValue({ languages: [] })
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
  refresh.mockReset()
})

async function openManager() {
  wrapper = mount(LanguagePacks)
  await wrapper.get('button[aria-expanded]').trigger('click')
  await flushPromises()
  return wrapper
}

async function selectFile(file: File) {
  const input = wrapper!.get('input[type="file"]')
  Object.defineProperty(input.element, 'files', { configurable: true, value: [file] })
  await input.trigger('change')
}

describe('language pack management', () => {
  it('loads language metadata only when the administrator opens management', async () => {
    wrapper = mount(LanguagePacks)
    expect(api.languagePacks).not.toHaveBeenCalled()
    await wrapper.get('button[aria-expanded]').trigger('click')
    await flushPromises()
    expect(api.languagePacks).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('No community language packs installed.')
  })

  it('installs a pack and refreshes live language choices without saving unrelated settings', async () => {
    const upload = vi.spyOn(api, 'languagePackUpload').mockResolvedValue(FRENCH)
    const save = vi.spyOn(api, 'adminUpdateConfig')
    await openManager()
    const file = new File(['ZIP data'], 'french.zip', { type: 'application/zip' })
    await selectFile(file)
    await wrapper!.get('form').trigger('submit')
    await flushPromises()
    expect(upload).toHaveBeenCalledWith(file, expect.any(AbortSignal))
    expect(refresh).toHaveBeenCalledExactlyOnceWith(true)
    expect(wrapper!.get('.pack-list').text()).toContain('Français')
    expect(wrapper!.get('.pack-success').text()).toBe('Français was installed.')
    expect(wrapper!.get('button[type="submit"]').attributes('disabled')).toBeDefined()
    expect(save).not.toHaveBeenCalled()
  })

  it('clears a selected file when collapsing instead of uploading a hidden prior selection', async () => {
    const upload = vi.spyOn(api, 'languagePackUpload')
    await openManager()
    await selectFile(new File(['ZIP data'], 'french.zip'))
    expect(wrapper!.get('button[type="submit"]').attributes('disabled')).toBeUndefined()
    await wrapper!.get('button[aria-expanded]').trigger('click')
    expect(wrapper!.find('input[type="file"]').exists()).toBe(false)
    await wrapper!.get('button[aria-expanded]').trigger('click')
    await flushPromises()
    expect((wrapper!.get('input[type="file"]').element as HTMLInputElement).value).toBe('')
    expect(wrapper!.get('button[type="submit"]').attributes('disabled')).toBeDefined()
    await wrapper!.get('form').trigger('submit')
    expect(upload).not.toHaveBeenCalled()
  })

  it('preserves successful installation while reporting a refresh that resolves with a runtime error', async () => {
    vi.spyOn(api, 'languagePackUpload').mockResolvedValue(FRENCH)
    refresh.mockImplementation(async () => { runtime.setError(true) })
    await openManager()
    await selectFile(new File(['ZIP data'], 'french.zip'))
    await wrapper!.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper!.get('.pack-list').text()).toContain('Français')
    expect(wrapper!.get('.pack-success').text()).toBe('Français was installed.')
    expect(wrapper!.text()).toContain('The change was saved. Language choices could not refresh yet')
    expect(wrapper!.find('[role="alert"]').exists()).toBe(false)

    runtime.setError(false)
    await flushPromises()
    expect(wrapper!.text()).not.toContain('Language choices could not refresh yet')
    expect(wrapper!.get('.pack-success').text()).toBe('Français was installed.')
  })

  it('treats a malformed language list as recoverable rather than claiming no packs are installed', async () => {
    vi.mocked(api.languagePacks)
      .mockResolvedValueOnce({ languages: [{ locale: 'fr' }] } as never)
      .mockResolvedValueOnce({ languages: [FRENCH] })
    await openManager()
    expect(wrapper!.get('[role="alert"]').text()).toContain('Could not load installed languages')
    expect(wrapper!.text()).not.toContain('No community language packs installed.')
    await wrapper!.findAll('button').find(button => button.text() === 'Refresh installed languages')!.trigger('click')
    await flushPromises()
    expect(wrapper!.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper!.get('.pack-list').text()).toContain('Français')
  })

  it('replaces a pack of the same locale rather than creating a second listing', async () => {
    vi.mocked(api.languagePacks).mockResolvedValue({ languages: [FRENCH] })
    vi.spyOn(api, 'languagePackUpload').mockResolvedValue({ ...FRENCH, version: '2.0', revision: 'two' })
    await openManager()
    await selectFile(new File(['ZIP data'], 'updated.zip'))
    await wrapper!.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper!.findAll('.pack-list li')).toHaveLength(1)
    expect(wrapper!.get('.pack-list').text()).toContain('Version 2.0')
  })

  it.each([
    new File(['not a zip'], 'french.json'),
    new File([], 'empty.zip'),
    new File([new Uint8Array(1024 * 1024 + 1)], 'large.zip'),
  ])('rejects invalid file selection before upload ($name)', async file => {
    const upload = vi.spyOn(api, 'languagePackUpload')
    await openManager()
    await selectFile(file)
    expect(wrapper!.get('[role="alert"]').text()).not.toBe('')
    expect(wrapper!.get('button[type="submit"]').attributes('disabled')).toBeDefined()
    expect(upload).not.toHaveBeenCalled()
  })

  it('retains the installed pack and selected file when a replacement fails', async () => {
    vi.mocked(api.languagePacks).mockResolvedValue({ languages: [FRENCH] })
    const upload = vi.spyOn(api, 'languagePackUpload')
      .mockRejectedValueOnce(new ApiError(400, 'Placeholder mismatch', undefined, 'invalid_language_pack'))
      .mockResolvedValueOnce({ ...FRENCH, version: '2.0', revision: 'two' })
    await openManager()
    const file = new File(['ZIP data'], 'replacement.zip')
    await selectFile(file)
    await wrapper!.get('form').trigger('submit')
    await flushPromises()
    expect(wrapper!.get('[role="alert"]').text()).toBe('Placeholder mismatch')
    expect(wrapper!.get('.pack-list').text()).toContain('Version 1.0')
    expect(refresh).not.toHaveBeenCalled()
    expect(wrapper!.get('button[type="submit"]').attributes('disabled')).toBeUndefined()
    await wrapper!.get('form').trigger('submit')
    await flushPromises()
    expect(upload.mock.calls[1]?.[0]).toBe(file)
    expect(wrapper!.get('.pack-list').text()).toContain('Version 2.0')
  })

  it('requires explicit inline confirmation before removing a pack', async () => {
    vi.mocked(api.languagePacks).mockResolvedValue({ languages: [FRENCH] })
    const remove = vi.spyOn(api, 'languagePackRemove').mockResolvedValue({ success: true })
    await openManager()
    await wrapper!.get('button[aria-label="Remove Français"]').trigger('click')
    expect(remove).not.toHaveBeenCalled()
    expect(wrapper!.get('.pack-confirmation').text()).toContain('Remove Français?')
    await wrapper!.get('.pack-confirmation .btn-danger').trigger('click')
    await flushPromises()
    expect(remove).toHaveBeenCalledWith('fr', expect.any(AbortSignal))
    expect(wrapper!.find('.pack-list').exists()).toBe(false)
    expect(refresh).toHaveBeenCalledExactlyOnceWith(true)
  })

  it('keeps a pack listed after removal fails and emits unauthorized for expired sessions', async () => {
    vi.mocked(api.languagePacks).mockResolvedValue({ languages: [FRENCH] })
    vi.spyOn(api, 'languagePackRemove').mockRejectedValue(new ApiError(401, 'Not authenticated', undefined))
    await openManager()
    await wrapper!.get('button[aria-label="Remove Français"]').trigger('click')
    await wrapper!.get('.pack-confirmation .btn-danger').trigger('click')
    await flushPromises()
    expect(wrapper!.get('.pack-list').text()).toContain('Français')
    expect(wrapper!.emitted('unauthorized')).toHaveLength(1)
    expect(refresh).not.toHaveBeenCalled()
  })

  it('discards and aborts work when the panel is unmounted', async () => {
    let finish!: (value: LanguagePackSummary) => void
    const upload = vi.spyOn(api, 'languagePackUpload').mockReturnValue(new Promise(resolve => { finish = resolve }))
    await openManager()
    await selectFile(new File(['ZIP data'], 'french.zip'))
    await wrapper!.get('form').trigger('submit')
    const signal = upload.mock.calls[0]?.[1]
    wrapper!.unmount()
    wrapper = undefined
    expect(signal?.aborted).toBe(true)
    finish(FRENCH)
    await flushPromises()
    expect(refresh).not.toHaveBeenCalled()
  })
})

describe('language pack API transport', () => {
  it('uploads a multipart file with the administrator cookie and reads a typed summary', async () => {
    const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(FRENCH), { status: 200 }))
    vi.stubGlobal('fetch', fetch)
    const file = new File(['ZIP data'], 'french.zip')
    await expect(api.languagePackUpload(file)).resolves.toEqual(FRENCH)
    const [url, init] = fetch.mock.calls[0]!
    expect(url).toBe('/api/admin/languages')
    expect(init.credentials).toBe('same-origin')
    expect(init.body.get('file')).toBe(file)
    expect(init.headers).toBeUndefined()
  })

  it('rejects malformed successful upload responses rather than reporting installation', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 200 })))
    await expect(api.languagePackUpload(new File(['ZIP'], 'french.zip')))
      .rejects.toThrow('Invalid language pack response')
  })

  it('returns authentication errors from a template download', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'Not authenticated' }), { status: 401 })))
    await expect(api.languagePackTemplate()).rejects.toMatchObject({ status: 401, message: 'Not authenticated' })
  })
})
