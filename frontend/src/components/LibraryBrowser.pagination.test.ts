import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import LibraryBrowser from './LibraryBrowser.vue'

/**
 * Alphabet-jump paging.
 *
 * An alphabet jump lands on a server-computed NameLessThan offset, which is
 * never page-aligned. The window then grows in both directions from an
 * arbitrary start, which is what made the arithmetic wrong: the upward fetch
 * always asked for a full page even when fewer rows were missing.
 */

const PAGE_SIZE = 50
const TOTAL = 300

function rowsFrom(startIndex: number, limit: number) {
  const end = Math.min(startIndex + limit, TOTAL)
  return {
    Items: Array.from({ length: Math.max(0, end - startIndex) }, (_, i) => ({
      Id: `item-${startIndex + i}`,
      Name: `Title ${String(startIndex + i).padStart(4, '0')}`,
      Type: 'Movie',
    })),
    TotalRecordCount: TOTAL,
    StartIndex: startIndex,
  }
}

let requests: Array<{ startIndex: number; limit: number }>

function mountBrowser() {
  return mount(LibraryBrowser, {
    global: {
      plugins: [createPinia()],
      stubs: { TitleDetails: true },
    },
  })
}

describe('alphabet-jump pagination', () => {
  beforeEach(() => {
    requests = []
    vi.stubGlobal('IntersectionObserver', class {
      observe() {}
      disconnect() {}
      unobserve() {}
    })
    // jsdom ships neither CSS.escape nor Element.scrollIntoView, and
    // jumpToLetter scrolls the landed row into view through both.
    vi.stubGlobal('CSS', { escape: (value: string) => value })
    Element.prototype.scrollIntoView = vi.fn()
    vi.spyOn(api, 'libraries').mockResolvedValue({
      Items: [{
        Id: 'library-1', Name: 'Movies', Type: 'CollectionFolder', CollectionType: 'movies',
      }],
      TotalRecordCount: 1,
    })
    vi.spyOn(api, 'itemPrefixes').mockResolvedValue({ Prefixes: ['A', 'M', 'Z'] })
    vi.spyOn(api, 'items').mockImplementation(async (params: Record<string, unknown>) => {
      const startIndex = Number(params.startIndex ?? 0)
      const limit = Number(params.limit ?? PAGE_SIZE)
      requests.push({ startIndex, limit })
      // An anchor jump answers from the server-computed offset, not the one
      // the caller asked for. 25 is deliberately not page-aligned.
      if (params.anchorPrefix) return rowsFrom(25, limit)
      return rowsFrom(startIndex, limit)
    })
  })

  afterEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('requests only the gap above the window, not a whole page', async () => {
    const wrapper = mountBrowser()
    await flushPromises()
    await wrapper.get('[aria-label="Open Movies"]').trigger('click')
    await flushPromises()

    await wrapper.get('button[aria-label="Jump to M"]').trigger('click')
    await flushPromises()

    const vm = wrapper.vm as unknown as {
      loadedStartIndex: number
      loadedCount: number
      items: Array<{ Id: string }>
    }
    expect(vm.loadedStartIndex).toBe(25)

    requests.length = 0
    await (wrapper.vm as unknown as { loadPrevious: () => Promise<unknown> }).loadPrevious()
    await flushPromises()

    // Rows 0-24 are missing, so the request must be 25 wide. Asking for 50
    // returned rows 0-49 and duplicated the 25 already held.
    expect(requests).toEqual([{ startIndex: 0, limit: 25 }])

    const ids = vm.items.map((item) => item.Id)
    expect(new Set(ids).size).toBe(ids.length)
  })

  it('does not skip a block when scrolling down after scrolling up', async () => {
    const wrapper = mountBrowser()
    await flushPromises()
    await wrapper.get('[aria-label="Open Movies"]').trigger('click')
    await flushPromises()
    await wrapper.get('button[aria-label="Jump to M"]').trigger('click')
    await flushPromises()

    const vm = wrapper.vm as unknown as {
      loadPrevious: () => Promise<unknown>
      loadMore: () => Promise<unknown>
      items: Array<{ Id: string }>
    }
    await vm.loadPrevious()
    await flushPromises()

    requests.length = 0
    await vm.loadMore()
    await flushPromises()

    // Window is rows 0-74 once the gap is filled, so the next page starts at
    // 75. Deriving it from items.length gave 100 and left 75-99 unreachable.
    expect(requests).toEqual([{ startIndex: 75, limit: PAGE_SIZE }])

    const ids = vm.items.map((item) => item.Id)
    expect(new Set(ids).size).toBe(ids.length)
    expect(ids).toContain('item-75')
  })
})
