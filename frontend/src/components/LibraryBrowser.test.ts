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
  it('shows and applies only Jellyfin-supported filter controls', async () => {
    vi.stubGlobal('IntersectionObserver', class {
      observe() {}
      disconnect() {}
    })
    localStorage.setItem('emby-watchparty-library-filters:library-1', JSON.stringify({
      filters: { tag: ['Hidden'], audio_codec: ['aac'] },
      sortField: 'SortName',
      sortDirection: 'Ascending',
    }))
    vi.spyOn(api, 'mediaServerInfo').mockResolvedValue({
      media_server_type: 'jellyfin',
      display_name: 'Jellyfin',
      capabilities: { filter_controls: true },
    })
    vi.spyOn(api, 'libraries').mockResolvedValue({
      Items: [{
        Id: 'library-1', Name: 'Movies', Type: 'CollectionFolder', CollectionType: 'movies',
      }],
      TotalRecordCount: 1,
    })
    const items = vi.spyOn(api, 'items').mockResolvedValue({
      Items: [{ Id: 'movie-1', Name: 'Arrival', Type: 'Movie' }],
      TotalRecordCount: 1,
    })
    const queryItems = vi.spyOn(api, 'queryItems').mockResolvedValue({
      Items: [{ Id: 'movie-1', Name: 'Arrival', Type: 'Movie' }],
      TotalRecordCount: 1,
    })
    vi.spyOn(api, 'filterOptions').mockResolvedValue({
      controls: [
        {
          id: 'playstate', label: 'Playstate', kind: 'select',
          values: [
            { value: 'any', label: 'Any' },
            { value: 'unplayed', label: 'Unplayed' },
            { value: 'played', label: 'Played' },
            { value: 'resumable', label: 'In progress' },
          ],
        },
        { id: 'favorite', label: 'Favorite', kind: 'toggle', values: [] },
        {
          id: 'genre', label: 'Genre', kind: 'multi',
          values: [{ value: 'Drama', label: 'Drama' }],
        },
        {
          id: 'studio', label: 'Studio', kind: 'multi',
          values: [{ value: 'Paramount', label: 'Paramount' }],
        },
        {
          id: 'year', label: 'Year', kind: 'multi',
          values: [{ value: '2020', label: '2020' }],
        },
        {
          id: 'official_rating', label: 'Parental rating', kind: 'multi',
          values: [{ value: 'PG-13', label: 'PG-13' }],
        },
        {
          id: 'community_rating', label: 'Community rating', kind: 'select',
          values: [{ value: '7', label: '7+' }],
        },
        {
          id: 'critic_rating', label: 'Critic rating', kind: 'select',
          values: [{ value: '80', label: '80%+' }],
        },
      ],
    })
    vi.spyOn(api, 'itemPrefixes').mockResolvedValue({ Prefixes: [] })
    vi.spyOn(api, 'queryPrefixes').mockResolvedValue({ Prefixes: [] })

    const wrapper = mount(LibraryBrowser, {
      global: { plugins: [createPinia()] },
    })
    await flushPromises()
    await wrapper.get('[aria-label="Open Movies"]').trigger('click')
    await flushPromises()

    expect(items).toHaveBeenCalled()
    expect(queryItems).not.toHaveBeenCalled()
    await wrapper.get('button.filter-toggle').trigger('click')
    await wrapper.get('button.advanced-toggle').trigger('click')
    const filterPanel = wrapper.get('.filter-panel').text()
    expect(filterPanel).toContain('Playstate')
    expect(filterPanel).toContain('Favorite')
    expect(filterPanel).toContain('Genre')
    expect(filterPanel).toContain('Studio')
    expect(filterPanel).toContain('Year')
    expect(filterPanel).toContain('Parental rating')
    expect(filterPanel).toContain('Community rating')
    expect(filterPanel).toContain('Critic rating')
    expect(filterPanel).not.toContain('Tags')
    expect(filterPanel).not.toContain('Codec')
    expect(wrapper.get('button.filter-toggle').text()).not.toContain('active')

    await wrapper.get('select[aria-label="Playstate"]').setValue('unplayed')
    await flushPromises()
    expect(queryItems).toHaveBeenLastCalledWith(expect.objectContaining({
      filters: { playstate: 'unplayed' },
    }), expect.any(AbortSignal))

    const favorite = wrapper.findAll('button.filter-choice')
      .find(button => button.text().includes('Favorite'))
    expect(favorite).toBeDefined()
    await favorite!.trigger('click')
    await wrapper.get('button[aria-label="Open Genre filter"]').trigger('click')
    await wrapper.get('input[value="Drama"]').setValue(true)
    await wrapper.get('button[aria-label="Open Studio filter"]').trigger('click')
    await wrapper.get('input[value="Paramount"]').setValue(true)
    await wrapper.get('button[aria-label="Open Year filter"]').trigger('click')
    await wrapper.get('button[aria-label="Year range mode"]').trigger('click')
    await wrapper.get('input[aria-label="Start year"]').setValue('2014')
    await wrapper.get('input[aria-label="End year"]').setValue('2021')
    await wrapper.get('button[aria-label="Apply year filter"]').trigger('click')
    await wrapper.get('button[aria-label="Open Parental rating filter"]').trigger('click')
    await wrapper.get('input[value="PG-13"]').setValue(true)
    await wrapper.get('select[aria-label="Community rating"]').setValue('7')
    await wrapper.get('select[aria-label="Critic rating"]').setValue('80')
    await flushPromises()

    expect(queryItems).toHaveBeenLastCalledWith(expect.objectContaining({
      filters: {
        playstate: 'unplayed',
        favorite: true,
        genres: ['Drama'],
        studios: ['Paramount'],
        years: [2014, 2015, 2016, 2017, 2018, 2019, 2020, 2021],
        official_ratings: ['PG-13'],
        community_rating_min: 7,
        critic_rating_min: 80,
      },
    }), expect.any(AbortSignal))

    await wrapper.get('button[aria-label="Open Year filter"]').trigger('click')
    await wrapper.get('button[aria-label="Exact year mode"]').trigger('click')
    await wrapper.get('input[aria-label="Exact year"]').setValue('1999')
    await wrapper.get('button[aria-label="Apply year filter"]').trigger('click')
    await flushPromises()
    expect(queryItems).toHaveBeenLastCalledWith(expect.objectContaining({
      filters: expect.objectContaining({ years: [1999] }),
    }), expect.any(AbortSignal))

    await wrapper.get('button[aria-label="Decade mode"]').trigger('click')
    await wrapper.get('select[aria-label="Year decade"]').setValue('2010')
    await wrapper.get('button[aria-label="Apply year filter"]').trigger('click')
    await flushPromises()
    expect(queryItems).toHaveBeenLastCalledWith(expect.objectContaining({
      filters: expect.objectContaining({
        years: [2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019],
      }),
    }), expect.any(AbortSignal))
    expect(JSON.parse(localStorage.getItem(
      'emby-watchparty-library-filters:library-1',
    ) || '{}').filters).toEqual(expect.objectContaining({
      tag: ['Hidden'], audio_codec: ['aac'],
    }))
  })

  it('keeps saved filters dormant when the selected provider does not support them', async () => {
    vi.stubGlobal('IntersectionObserver', class {
      observe() {}
      disconnect() {}
    })
    localStorage.setItem('emby-watchparty-library-filters:library-1', JSON.stringify({
      filters: { genre: ['Drama'] },
      sortField: 'SortName',
      sortDirection: 'Ascending',
    }))
    vi.spyOn(api, 'mediaServerInfo').mockResolvedValue({
      media_server_type: 'jellyfin',
      display_name: 'Jellyfin',
      capabilities: { filter_controls: false },
    })
    vi.spyOn(api, 'libraries').mockResolvedValue({
      Items: [{
        Id: 'library-1', Name: 'Movies', Type: 'CollectionFolder', CollectionType: 'movies',
      }],
      TotalRecordCount: 1,
    })
    const items = vi.spyOn(api, 'items').mockResolvedValue({
      Items: [{ Id: 'movie-1', Name: 'Arrival', Type: 'Movie' }],
      TotalRecordCount: 1,
    })
    const queryItems = vi.spyOn(api, 'queryItems').mockResolvedValue({
      Items: [{ Id: 'movie-1', Name: 'Arrival', Type: 'Movie' }],
      TotalRecordCount: 1,
    })
    const filterOptions = vi.spyOn(api, 'filterOptions').mockResolvedValue({ controls: [] })
    vi.spyOn(api, 'itemPrefixes').mockResolvedValue({ Prefixes: [] })
    vi.spyOn(api, 'queryPrefixes').mockResolvedValue({ Prefixes: [] })

    const wrapper = mount(LibraryBrowser, {
      global: { plugins: [createPinia()] },
    })
    await flushPromises()
    expect(wrapper.text()).toContain('Browse your Jellyfin media')
    expect(wrapper.text()).not.toContain('Browse your Emby media')
    await wrapper.get('[aria-label="Open Movies"]').trigger('click')
    await flushPromises()

    expect(wrapper.find('.library-filters').exists()).toBe(false)
    expect(wrapper.find('select[aria-label="Sort titles"]').exists()).toBe(true)
    expect(filterOptions).not.toHaveBeenCalled()
    expect(items).toHaveBeenCalled()
    expect(queryItems).not.toHaveBeenCalled()

    await wrapper.get('select[aria-label="Sort titles"]').setValue('ProductionYear')
    await flushPromises()

    expect(queryItems).toHaveBeenLastCalledWith(expect.objectContaining({
      filters: {},
      sort: expect.objectContaining({ field: 'ProductionYear' }),
    }), expect.any(AbortSignal))
    expect(JSON.parse(localStorage.getItem(
      'emby-watchparty-library-filters:library-1',
    ) || '{}').filters).toEqual({ genre: ['Drama'] })
  })

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
