import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import LibraryBrowser from './LibraryBrowser.vue'

afterEach(() => {
  localStorage.clear()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('LibraryBrowser search routing', () => {
  it('opens movie details from a grouped global-search result', async () => {
    vi.stubGlobal('IntersectionObserver', class {
      observe() {}
      disconnect() {}
    })
    vi.spyOn(api, 'libraries').mockResolvedValue({ Items: [], TotalRecordCount: 0 })
    vi.spyOn(api, 'groupedSearch').mockResolvedValue({
      query: 'spiderman',
      groups: [{
        id: 'movies',
        label: 'Movies',
        items: [{ Id: 'movie-1', Name: 'Spider-Man', Type: 'Movie' }],
      }],
    })

    const wrapper = mount(LibraryBrowser, {
      global: {
        plugins: [createPinia()],
        stubs: {
          TitleDetails: {
            props: ['item'],
            template: '<div data-testid="details">{{ item.Name }}</div>',
          },
        },
      },
    })
    await flushPromises()

    const input = wrapper.get('input[aria-label="Search all libraries"]')
    await input.setValue('spiderman')
    await input.trigger('keydown.enter')
    await flushPromises()
    await wrapper.get('button[data-item-id="movie-1"]').trigger('click')

    expect(wrapper.get('[data-testid="details"]').text()).toBe('Spider-Man')
  })

  it('live-filters the open library when fuzzy search resolves to a person', async () => {
    vi.stubGlobal('IntersectionObserver', class {
      observe() {}
      disconnect() {}
    })
    vi.spyOn(api, 'libraries').mockResolvedValue({
      Items: [{
        Id: 'library-1', Name: 'Movies', Type: 'CollectionFolder', CollectionType: 'movies',
      }],
      TotalRecordCount: 1,
    })
    vi.spyOn(api, 'items').mockResolvedValue({
      Items: [{ Id: 'unrelated-1', Name: 'Unrelated Movie', Type: 'Movie' }],
      TotalRecordCount: 1,
    })
    vi.spyOn(api, 'filterOptions').mockResolvedValue({ controls: [] })
    vi.spyOn(api, 'itemPrefixes').mockResolvedValue({ Prefixes: [] })
    vi.spyOn(api, 'groupedSearch').mockResolvedValue({
      query: 'sean conery',
      groups: [{
        id: 'people',
        label: 'People',
        items: [{ Id: 'person-1', Name: 'Sean Connery', Type: 'Person' }],
      }],
    })
    const queryItems = vi.spyOn(api, 'queryItems').mockResolvedValue({
      Items: [{ Id: 'bond-1', Name: 'Goldfinger', Type: 'Movie' }],
      TotalRecordCount: 1,
    })

    const wrapper = mount(LibraryBrowser, {
      global: { plugins: [createPinia()] },
    })
    await flushPromises()
    await wrapper.get('[aria-label="Open Movies"]').trigger('click')
    await flushPromises()

    const input = wrapper.get('input[aria-label="Search all libraries"]')
    await input.setValue('sean conery')
    await input.trigger('keydown.enter')
    await flushPromises()

    expect(queryItems).toHaveBeenCalledWith(expect.objectContaining({
      scope: expect.objectContaining({ parent_id: 'library-1' }),
      filters: expect.objectContaining({ person_ids: ['person-1'] }),
    }), expect.any(AbortSignal))
    expect(wrapper.text()).toContain('Goldfinger')
    expect(wrapper.text()).not.toContain('Unrelated Movie')
  })

  it('live-filters direct title matches and restores the library when cleared', async () => {
    vi.stubGlobal('CSS', { escape: (value: string) => value })
    vi.stubGlobal('IntersectionObserver', class {
      observe() {}
      disconnect() {}
    })
    vi.spyOn(api, 'libraries').mockResolvedValue({
      Items: [{
        Id: 'library-1', Name: 'Movies', Type: 'CollectionFolder', CollectionType: 'movies',
      }],
      TotalRecordCount: 1,
    })
    vi.spyOn(api, 'items').mockResolvedValue({
      Items: [{ Id: 'unrelated-1', Name: 'Unrelated Movie', Type: 'Movie' }],
      TotalRecordCount: 1,
    })
    vi.spyOn(api, 'filterOptions').mockResolvedValue({ controls: [] })
    vi.spyOn(api, 'itemPrefixes').mockResolvedValue({ Prefixes: [] })
    vi.spyOn(api, 'groupedSearch').mockResolvedValue({
      query: 'matrix',
      groups: [{
        id: 'movies', label: 'Movies',
        items: [{ Id: 'matrix-1', Name: 'The Matrix', Type: 'Movie' }],
      }],
    })

    const wrapper = mount(LibraryBrowser, {
      global: {
        plugins: [createPinia()],
        stubs: {
          TitleDetails: {
            props: ['item'],
            emits: ['back'],
            template: '<div><span data-testid="details">{{ item.Name }}</span><button aria-label="Back from details" @click="$emit(\'back\')">Back</button></div>',
          },
        },
      },
    })
    await flushPromises()
    await wrapper.get('[aria-label="Open Movies"]').trigger('click')
    await flushPromises()

    const input = wrapper.get('input[aria-label="Search all libraries"]')
    await input.setValue('matrix')
    await input.trigger('keydown.enter')
    await flushPromises()
    expect(wrapper.text()).toContain('The Matrix')
    expect(wrapper.text()).not.toContain('Unrelated Movie')

    const clearButton = wrapper.findAll('button').find((button) => button.text() === 'Clear')
    expect(clearButton).toBeDefined()
    await clearButton!.trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Unrelated Movie')
    expect(wrapper.text()).not.toContain('The Matrix')

    await input.setValue('matrix')
    await input.trigger('keydown.enter')
    await flushPromises()
    await wrapper.get('[aria-label="Open The Matrix"]').trigger('click')
    await wrapper.get('[aria-label="Back from details"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Unrelated Movie')
    expect(wrapper.get('input[aria-label="Search all libraries"]').element).toHaveProperty('value', '')
  })

  it('shows a load error instead of claiming a failed filter has no results', async () => {
    vi.stubGlobal('IntersectionObserver', class {
      observe() {}
      disconnect() {}
    })
    vi.spyOn(api, 'libraries').mockResolvedValue({
      Items: [{
        Id: 'library-1', Name: 'Movies', Type: 'CollectionFolder', CollectionType: 'movies',
      }],
      TotalRecordCount: 1,
    })
    vi.spyOn(api, 'items').mockResolvedValue({
      Items: [{ Id: 'movie-1', Name: 'Drama Movie', Type: 'Movie' }],
      TotalRecordCount: 1,
    })
    vi.spyOn(api, 'filterOptions').mockResolvedValue({
      controls: [{
        id: 'genre', label: 'Genre', kind: 'multi',
        values: [{ value: 'Drama', label: 'Drama' }],
      }],
    })
    vi.spyOn(api, 'itemPrefixes').mockResolvedValue({ Prefixes: [] })
    const queryItems = vi.spyOn(api, 'queryItems').mockRejectedValue(new Error('Server failed'))

    const wrapper = mount(LibraryBrowser, {
      global: { plugins: [createPinia()] },
    })
    await flushPromises()
    await wrapper.get('[aria-label="Open Movies"]').trigger('click')
    await flushPromises()
    await wrapper.get('button.filter-toggle').trigger('click')
    await wrapper.get('button[aria-label="Open Genre filter"]').trigger('click')
    await wrapper.get('input[value="Drama"]').setValue(true)
    await flushPromises()

    // Scope is deliberately empty: the backend resolves item types from the
    // library's collection type, the same resolver the unfiltered browse uses.
    // This previously asserted a second copy of that map maintained here, which
    // sent MediaTypes=Video for TV libraries and matched zero rows upstream.
    expect(queryItems).toHaveBeenCalledWith(expect.objectContaining({
      scope: {
        parent_id: 'library-1',
        include_item_types: [],
        media_types: [],
        recursive: false,
      },
    }), expect.any(AbortSignal))
    expect(wrapper.get('[role="alert"]').text()).toContain('Could not load library')
    expect(wrapper.text()).not.toContain('No items found.')
  })
})
