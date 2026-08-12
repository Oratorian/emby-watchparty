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
    await wrapper.get('button[data-section="seasons"]').trigger('click')
    await flushPromises()

    // A seasons failure leaves seasonsLoaded false, so an error rendered only
    // inside the loaded branch was invisible in exactly the case it existed
    // for: the button did nothing and said nothing.
    expect(wrapper.get('[role="alert"]').text()).toContain('Seasons unavailable.')
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

      await wrapper.get('.optional-sections').trigger('mouseleave')
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

      await wrapper.get('.optional-sections').trigger('mouseleave')
      await vi.advanceTimersByTimeAsync(200)
      await wrapper.get('.optional-sections').trigger('mouseenter')
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

    await wrapper.get('.optional-sections').trigger('keydown.esc')

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
