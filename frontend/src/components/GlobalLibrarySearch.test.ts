import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import GlobalLibrarySearch from './GlobalLibrarySearch.vue'

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('GlobalLibrarySearch', () => {
  it('debounces two-character searches, cancels stale work, and submits Enter immediately', async () => {
    vi.useFakeTimers()
    const groupedSearch = vi.spyOn(api, 'groupedSearch').mockResolvedValue({
      query: 'matrix',
      groups: [{
        id: 'movies',
        label: 'Movies',
        items: [{ Id: 'movie-1', Name: 'Matrix', Type: 'Movie' }],
      }],
    })
    const wrapper = mount(GlobalLibrarySearch)
    const input = wrapper.get('input[aria-label="Search all libraries"]')

    await input.setValue('m')
    await vi.advanceTimersByTimeAsync(300)
    expect(groupedSearch).not.toHaveBeenCalled()

    await input.setValue('ma')
    await vi.advanceTimersByTimeAsync(300)
    expect(groupedSearch).toHaveBeenCalledTimes(1)

    await input.setValue('matrix')
    await input.trigger('keydown.enter')
    expect(groupedSearch).toHaveBeenCalledTimes(2)
    expect((groupedSearch.mock.calls[0]?.[1] as AbortSignal).aborted).toBe(true)

    await vi.runAllTimersAsync()
    expect(wrapper.text()).toContain('Movies')
    await wrapper.get('button[data-item-id="movie-1"]').trigger('click')
    expect(wrapper.emitted('select')?.[0]?.[0]).toMatchObject({ Id: 'movie-1' })
  })
})
