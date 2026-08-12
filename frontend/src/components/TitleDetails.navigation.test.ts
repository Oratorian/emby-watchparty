import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import TitleDetails from './TitleDetails.vue'

/**
 * This component is REUSED across item navigation rather than re-created, so
 * anything not explicitly reset belongs to the title the user just left.
 */

const SERIES = {
  Id: 'series-1',
  Name: 'A Series',
  Type: 'Series',
  TagItems: [{ Id: 'tag-1', Name: 'Featured' }],
}
const EPISODE = { Id: 'episode-1', Name: 'An Episode', Type: 'Episode' }

describe('TitleDetails across item navigation', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api, 'itemDetails').mockImplementation(async (id: string) =>
      (id === 'series-1' ? SERIES : EPISODE) as never)
    vi.spyOn(api, 'qualityOptions').mockResolvedValue({
      options: [{ id: 'auto', label: 'Auto' }],
      default_id: 'auto',
    } as never)
  })

  it('refetches the optional sections instead of showing the previous title', async () => {
    const itemSection = vi.spyOn(api, 'itemSection').mockImplementation(
      async (id: string, section: string) => ({
        section,
        items: [{ Id: `${id}-${section}`, Name: `${id} ${section}`, Type: 'Movie' }],
      }) as never,
    )

    const wrapper = mount(TitleDetails, {
      props: { item: { Id: 'series-1', Name: 'A Series', Type: 'Series' }, isHost: false },
    })
    await flushPromises()
    await wrapper.get('button[data-section="related"]').trigger('click')
    await vi.waitFor(() => expect(wrapper.text()).toContain('series-1 related'))

    await wrapper.setProps({ item: EPISODE })
    await flushPromises()

    // The series' Related must be gone. loadSection early-returns when a
    // section is already populated, so without a reset the episode rendered
    // the series' rows and could never refetch its own.
    expect(wrapper.text()).not.toContain('series-1 related')

    itemSection.mockClear()
    await wrapper.get('button[data-section="related"]').trigger('click')
    await vi.waitFor(() => expect(wrapper.text()).toContain('episode-1 related'))
    expect(itemSection).toHaveBeenCalledWith('episode-1', 'related', expect.any(AbortSignal))
  })

  it('surfaces a seasons failure instead of doing nothing visible', async () => {
    vi.spyOn(api, 'seriesSeasons').mockRejectedValue(new Error('Seasons unavailable.'))

    const wrapper = mount(TitleDetails, {
      props: { item: { Id: 'series-1', Name: 'A Series', Type: 'Series' }, isHost: false },
    })
    await flushPromises()

    // A seasons failure leaves seasonsLoaded false, so an error rendered only
    // inside the loaded branch was invisible in exactly the case it existed
    // for: nothing happened and nothing was said. Seasons now load with the
    // title, so the failure surfaces without anyone pressing anything, and the
    // button survives purely as the way back from it.
    expect(wrapper.get('[role="alert"]').text()).toContain('Seasons unavailable.')
    expect(wrapper.get('button[data-section="seasons"]').text()).toBe('Retry')
  })

  it('renders tags from the field Emby actually sends', async () => {
    const wrapper = mount(TitleDetails, {
      props: { item: { Id: 'series-1', Name: 'A Series', Type: 'Series' }, isHost: false },
    })
    await flushPromises()

    // Emby 4.9.5.0 sends TagItems, not a flat Tags array. Reading Tags meant
    // the section never rendered for any title.
    expect(wrapper.text()).toContain('Featured')
  })
})

describe('the More section popover', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api, 'itemDetails').mockImplementation(async (id: string) =>
      (id === 'series-1' ? SERIES : EPISODE) as never)
    vi.spyOn(api, 'qualityOptions').mockResolvedValue({
      options: [{ id: 'auto', label: 'Auto' }],
      default_id: 'auto',
    } as never)
    vi.spyOn(api, 'itemSection').mockImplementation(async (_id: string, section: string) => ({
      section,
      items: section === 'related'
        ? [{ Id: 'related-1', Name: 'Rocky II', Type: 'Movie' }]
        : [],
    }) as never)
  })

  async function openDetails() {
    const wrapper = mount(TitleDetails, {
      props: { item: { Id: 'series-1', Name: 'A Series', Type: 'Series' }, isHost: false },
    })
    await flushPromises()
    return wrapper
  }

  it('shows one section at a time instead of stacking them', async () => {
    // Reported from a real session: each button rendered its own block below,
    // so opening all three left all three on screen at once, with two
    // "None available." lines trailing the one list that had content.
    const wrapper = await openDetails()

    await wrapper.get('button[data-section="related"]').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Rocky II')

    await wrapper.get('button[data-section="extras"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).not.toContain('Rocky II')
    expect(wrapper.findAll('.section-popover')).toHaveLength(1)
    expect(wrapper.text()).toContain('None available.')
  })

  it('closes when the same button is pressed again', async () => {
    const wrapper = await openDetails()

    await wrapper.get('button[data-section="related"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('.section-popover').exists()).toBe(true)

    await wrapper.get('button[data-section="related"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('.section-popover').exists()).toBe(false)
  })

  it('closes when the pointer leaves, after a grace period', async () => {
    vi.useFakeTimers()
    try {
      const wrapper = await openDetails()
      await wrapper.get('button[data-section="related"]').trigger('click')
      await flushPromises()

      await wrapper.get('.detail-toolbar').trigger('mouseleave')
      // Not immediately: moving diagonally towards the panel briefly exits
      // the group, and closing on that would make it unusable.
      expect(wrapper.find('.section-popover').exists()).toBe(true)

      await vi.advanceTimersByTimeAsync(500)
      expect(wrapper.find('.section-popover').exists()).toBe(false)
    } finally {
      vi.useRealTimers()
    }
  })

  it('stays open if the pointer comes back before the grace period ends', async () => {
    vi.useFakeTimers()
    try {
      const wrapper = await openDetails()
      await wrapper.get('button[data-section="related"]').trigger('click')
      await flushPromises()

      await wrapper.get('.detail-toolbar').trigger('mouseleave')
      await vi.advanceTimersByTimeAsync(200)
      await wrapper.get('.detail-toolbar').trigger('mouseenter')
      await vi.advanceTimersByTimeAsync(1000)

      expect(wrapper.find('.section-popover').exists()).toBe(true)
    } finally {
      vi.useRealTimers()
    }
  })

  it('closes on Escape, which is the only exit a keyboard user has', async () => {
    const wrapper = await openDetails()
    await wrapper.get('button[data-section="related"]').trigger('click')
    await flushPromises()

    await wrapper.get('.detail-toolbar').trigger('keydown.esc')

    expect(wrapper.find('.section-popover').exists()).toBe(false)
  })

  it('does not carry the panel across item navigation', async () => {
    const wrapper = await openDetails()
    await wrapper.get('button[data-section="related"]').trigger('click')
    await flushPromises()
    expect(wrapper.find('.section-popover').exists()).toBe(true)

    await wrapper.setProps({ item: EPISODE })
    await flushPromises()

    expect(wrapper.find('.section-popover').exists()).toBe(false)
  })
})

describe('the More popover presentation', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api, 'itemDetails').mockResolvedValue(SERIES as never)
    vi.spyOn(api, 'qualityOptions').mockResolvedValue({
      options: [{ id: 'auto', label: 'Auto' }],
      default_id: 'auto',
    } as never)
    vi.spyOn(api, 'itemSection').mockResolvedValue({
      section: 'related',
      items: [
        {
          Id: 'rocky-2',
          Name: 'Rocky II',
          Type: 'Movie',
          ProductionYear: 1979,
          RunTimeTicks: 71_400_000_000,
          ImageTags: { Primary: 'abc' },
        },
        { Id: 'brink', Name: 'The Brink of War', Type: 'Episode' },
      ],
    } as never)
  })

  async function openRelated() {
    const wrapper = mount(TitleDetails, {
      props: { item: { Id: 'series-1', Name: 'A Series', Type: 'Series' }, isHost: false },
    })
    await flushPromises()
    await wrapper.get('button[data-section="related"]').trigger('click')
    await flushPromises()
    return wrapper
  }

  it('formats each row with year, runtime and a poster', async () => {
    const wrapper = await openRelated()

    const rows = wrapper.findAll('.section-item')
    expect(rows).toHaveLength(2)
    // 1979 and 1h 59m, rather than a bare bulleted title.
    expect(rows[0]!.text()).toContain('Rocky II')
    expect(rows[0]!.text()).toContain('1979')
    expect(rows[0]!.text()).toContain('1h 59m')
    expect(rows[0]!.find('img').attributes('src')).toContain('rocky-2')
  })

  it('omits the type when it adds nothing, and keeps it when it does', async () => {
    const wrapper = await openRelated()
    const rows = wrapper.findAll('.section-item')

    // Every row in a Related list is usually a Movie; repeating it is noise.
    expect(rows[0]!.text()).not.toContain('Movie')
    expect(rows[1]!.text()).toContain('Episode')
  })

  it('falls back to an initial when the item has no poster', async () => {
    const wrapper = await openRelated()
    const rows = wrapper.findAll('.section-item')

    expect(rows[1]!.find('img').exists()).toBe(false)
    expect(rows[1]!.get('.section-thumb-fallback').text()).toBe('T')
  })

  it('offers a close control for pointer users who never leave the panel', async () => {
    const wrapper = await openRelated()

    await wrapper.get('.section-close').trigger('click')

    expect(wrapper.find('.section-popover').exists()).toBe(false)
  })
})

describe('the seasons and episodes pickers', () => {
  const SEASONS = [
    { Id: 'season-1', Name: 'Season 1', Type: 'Season' },
    { Id: 'season-2', Name: 'Season 2', Type: 'Season' },
  ]
  const S1 = [
    { Id: 'ep-1', Name: 'Maomao', Type: 'Episode', IndexNumber: 1 },
    { Id: 'ep-2', Name: 'Chilly Apothecary', Type: 'Episode', IndexNumber: 2 },
  ]
  const S2 = [{ Id: 'ep-25', Name: 'The New Pure Consort', Type: 'Episode', IndexNumber: 1 }]

  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api, 'itemDetails').mockResolvedValue({
      Id: 'series-1', Name: 'A Series', Type: 'Series',
    } as never)
    vi.spyOn(api, 'qualityOptions').mockResolvedValue({
      options: [{ id: 'auto', label: 'Auto' }], default_id: 'auto',
    } as never)
    vi.spyOn(api, 'seriesSeasons').mockResolvedValue({ items: SEASONS } as never)
    vi.spyOn(api, 'seriesEpisodes').mockImplementation(
      async (_series: string, seasonId?: string) =>
        ({ items: seasonId === 'season-2' ? S2 : S1 }) as never,
    )
  })

  async function loadedSeries() {
    const wrapper = mount(TitleDetails, {
      props: { item: { Id: 'series-1', Name: 'A Series', Type: 'Series' }, isHost: false },
    })
    await flushPromises()
    // No click: seasons load with the title now.
    return wrapper
  }

  it('offers seasons and episodes as two selects, not a wall of rows', async () => {
    // Reported from a real series: Load seasons rendered every episode of the
    // season as its own stacked row, which for a 24-episode season pushed the
    // rest of the page out of view entirely.
    const wrapper = await loadedSeries()

    expect(wrapper.get('select[aria-label="Season"]').findAll('option')).toHaveLength(2)
    // Episode options plus the placeholder.
    expect(wrapper.get('select[aria-label="Episode"]').findAll('option')).toHaveLength(3)
    expect(wrapper.findAll('button[data-episode-id]')).toHaveLength(0)
  })

  it('numbers each episode so a title alone is not the only handle', async () => {
    const wrapper = await loadedSeries()

    const options = wrapper.get('select[aria-label="Episode"]').findAll('option')
    expect(options[1]!.text()).toBe('1. Maomao')
    expect(options[2]!.text()).toBe('2. Chilly Apothecary')
  })

  it('replaces the episode list when another season is picked', async () => {
    const wrapper = await loadedSeries()

    await wrapper.get('select[aria-label="Season"]').setValue('season-2')
    await flushPromises()

    const text = wrapper.get('select[aria-label="Episode"]').text()
    expect(text).toContain('The New Pure Consort')
    // The previous season's episodes must be gone, not merely appended to.
    expect(text).not.toContain('Maomao')
  })

  it('opens the chosen episode and resets the control', async () => {
    const wrapper = await loadedSeries()

    await wrapper.get('select[aria-label="Episode"]').setValue('ep-2')
    await flushPromises()

    expect(wrapper.emitted('open')?.[0]?.[0]).toMatchObject({ Id: 'ep-2' })

    // The control resets, so the same episode can be chosen again. A select
    // that kept its value would not fire change a second time, which is the
    // behaviour that matters rather than what the DOM node reads.
    await wrapper.get('select[aria-label="Episode"]').setValue('ep-2')
    await flushPromises()
    expect(wrapper.emitted('open')).toHaveLength(2)
  })

  it('reports how many episodes the season has', async () => {
    const wrapper = await loadedSeries()
    expect(wrapper.get('.series-count').text()).toBe('2 Episodes')

    await wrapper.get('select[aria-label="Season"]').setValue('season-2')
    await flushPromises()
    expect(wrapper.get('.series-count').text()).toBe('1 Episode')
  })
})
