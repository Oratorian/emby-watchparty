import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import LibraryBrowser from './LibraryBrowser.vue'

/**
 * A navigation abort is not a load failure.
 *
 * /api/v2/items/filter-options fans out to ten media-server catalogue endpoints, so it is
 * the slowest request on the page and the most likely to still be in flight
 * when navigation aborts the shared controller. Treating that as a failure
 * emptied filterControls, and because configureFilters is memoised on
 * configuredParentId and nothing reset it, the panel stayed empty for that
 * library for the rest of the session.
 *
 * filterState is restored from localStorage BEFORE the fetch and survived the
 * wipe, so a saved filter kept filtering the grid with no chips, no active
 * count and no Reset All to clear it.
 */

const CONTROLS = [
  { id: 'genre', label: 'Genre', kind: 'multi' as const, values: [{ value: 'Drama', label: 'Drama' }] },
]

function abortError() {
  const error = new Error('The operation was aborted.')
  error.name = 'AbortError'
  return error
}

function mountBrowser() {
  return mount(LibraryBrowser, {
    global: { plugins: [createPinia()], stubs: { TitleDetails: true } },
  })
}

describe('filter panel across a navigation abort', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.stubGlobal('IntersectionObserver', class {
      observe() {}
      disconnect() {}
      unobserve() {}
    })
    vi.spyOn(api, 'libraries').mockResolvedValue({
      Items: [{ Id: 'library-1', Name: 'Movies', Type: 'CollectionFolder', CollectionType: 'movies' }],
      TotalRecordCount: 1,
    })
    vi.spyOn(api, 'items').mockResolvedValue({
      Items: [{ Id: 'movie-1', Name: 'A Movie', Type: 'Movie' }],
      TotalRecordCount: 1,
      StartIndex: 0,
    })
    vi.spyOn(api, 'itemPrefixes').mockResolvedValue({ Prefixes: [] })
  })

  afterEach(() => {
    localStorage.clear()
    vi.unstubAllGlobals()
  })

  it('retries the filter fetch instead of leaving the panel permanently empty', async () => {
    const filterOptions = vi.spyOn(api, 'filterOptions')
      // First visit: aborted by navigation while in flight.
      .mockRejectedValueOnce(abortError())
      // Second visit must be attempted at all, which is the point.
      .mockResolvedValueOnce({ controls: CONTROLS })

    const wrapper = mountBrowser()
    await flushPromises()
    await wrapper.get('[aria-label="Open Movies"]').trigger('click')
    await flushPromises()

    expect(filterOptions).toHaveBeenCalledTimes(1)

    // Leave the library and come back, the way a user recovers from this.
    await (wrapper.vm as unknown as { goToRoot: () => void }).goToRoot()
    await flushPromises()
    await wrapper.get('[aria-label="Open Movies"]').trigger('click')
    await flushPromises()

    // Memoised on configuredParentId, which the abort must clear. Without
    // that, this second visit never refetches and the panel stays empty.
    expect(filterOptions).toHaveBeenCalledTimes(2)
    const vm = wrapper.vm as unknown as { filterControls: typeof CONTROLS }
    expect(vm.filterControls).toHaveLength(1)
  })

  it('still surfaces a real filter failure rather than hiding it', async () => {
    // The abort path must not swallow genuine errors: a 500 here should still
    // empty the controls, which is the pre-existing behaviour.
    vi.spyOn(api, 'filterOptions').mockRejectedValue(new Error('Server failed'))

    const wrapper = mountBrowser()
    await flushPromises()
    await wrapper.get('[aria-label="Open Movies"]').trigger('click')
    await flushPromises()

    const vm = wrapper.vm as unknown as { filterControls: unknown[] }
    expect(vm.filterControls).toEqual([])
  })
})
