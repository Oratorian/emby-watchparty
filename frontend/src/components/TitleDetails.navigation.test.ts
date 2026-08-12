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
