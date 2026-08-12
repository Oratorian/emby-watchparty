import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import GlobalLibrarySearch from './GlobalLibrarySearch.vue'

describe('GlobalLibrarySearch recovery paths', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.restoreAllMocks()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('does not report a superseded search as a failure', async () => {
    // cancel() nulls the shared controller, so the abort guard read undefined
    // and every keystroke that superseded an in-flight search raised a
    // user-facing "Search unavailable." that nothing ever cleared.
    vi.spyOn(api, 'groupedSearch').mockImplementation(
      (_query: string, signal?: AbortSignal) =>
        new Promise((_resolve, reject) => {
          signal?.addEventListener('abort', () => {
            const error = new Error('The operation was aborted.')
            error.name = 'AbortError'
            reject(error)
          })
        }) as never,
    )

    const wrapper = mount(GlobalLibrarySearch)
    const input = wrapper.get('input[aria-label="Search all libraries"]')

    await input.setValue('spid')
    await vi.advanceTimersByTimeAsync(350)
    await input.setValue('spider')
    await flushPromises()

    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('does report a search that genuinely failed', async () => {
    // The other half of the same guard, and the reason it cannot simply
    // swallow everything. Asserting only that the banner stays absent is
    // satisfied by a component with no error branch at all -- a search
    // against a dead Emby would then look identical to one that found
    // nothing, and the operator would be debugging an empty library.
    vi.spyOn(api, 'groupedSearch').mockRejectedValue(new Error('Emby upstream unavailable'))

    const wrapper = mount(GlobalLibrarySearch)
    const input = wrapper.get('input[aria-label="Search all libraries"]')

    await input.setValue('spider')
    await vi.advanceTimersByTimeAsync(350)
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toBe('Emby upstream unavailable')
    // And the spinner is gone, so it does not read as still searching.
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
  })

  it('clears a previous failure once a search succeeds', async () => {
    const search = vi.spyOn(api, 'groupedSearch')
      .mockRejectedValueOnce(new Error('Emby upstream unavailable'))
      .mockResolvedValue({ groups: [], query: 'spider' } as never)

    const wrapper = mount(GlobalLibrarySearch)
    const input = wrapper.get('input[aria-label="Search all libraries"]')

    await input.setValue('spider')
    await vi.advanceTimersByTimeAsync(350)
    await flushPromises()
    expect(wrapper.find('[role="alert"]').exists()).toBe(true)

    await input.setValue('spiderman')
    await vi.advanceTimersByTimeAsync(350)
    await flushPromises()

    // A banner that outlives the failure that raised it is the bug the abort
    // guard above was written for, from the other direction.
    expect(search).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('reports an empty query when the input drops below the minimum length', async () => {
    // The parent restores the library when the query is empty. Sending the
    // single character instead read as a live search matching nothing, which
    // wiped the grid to "No items found." on the way down from two to one.
    const wrapper = mount(GlobalLibrarySearch)
    const input = wrapper.get('input[aria-label="Search all libraries"]')

    await input.setValue('sp')
    await input.setValue('s')
    await flushPromises()

    const emitted = wrapper.emitted('results') ?? []
    const last = emitted.at(-1)?.[0] as { query: string; groups: unknown[] }
    expect(last.query).toBe('')
    expect(last.groups).toEqual([])
  })
})
