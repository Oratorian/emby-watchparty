import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import TitleDetails from './TitleDetails.vue'

describe('TitleDetails', () => {
  it('loads rich metadata and routes playback from a dedicated detail view', async () => {
    vi.spyOn(api, 'itemDetails').mockResolvedValue({
      Id: 'movie-1',
      Name: 'Artifact Movie',
      Type: 'Movie',
      Taglines: ['A real fixture tagline'],
      CommunityRating: 8.2,
      OfficialRating: 'PG-13',
      RunTimeTicks: 7_200_000_000,
      Genres: ['Drama'],
      Overview: 'Artifact overview',
      People: [{ Id: 'person-1', Name: 'Actor', Type: 'Actor' }],
      Studios: [{ Id: 'studio-1', Name: 'Studio A' }],
      Tags: ['Featured'],
    })
    const itemSection = vi.spyOn(api, 'itemSection').mockResolvedValue({
      section: 'related',
      items: [{ Id: 'movie-2', Name: 'Related Movie', Type: 'Movie' }],
    })
    const wrapper = mount(TitleDetails, {
      props: {
        item: { Id: 'movie-1', Name: 'Artifact Movie', Type: 'Movie' },
        isHost: false,
      },
    })

    await vi.waitFor(() => expect(wrapper.text()).toContain('Artifact overview'))
    expect(wrapper.text()).toContain('A real fixture tagline')
    expect(wrapper.text()).toContain('8.2')
    expect(wrapper.text()).toContain('PG-13')
    expect(wrapper.text()).toContain('Drama')
    expect(wrapper.text()).toContain('Actor')
    expect(wrapper.find('[aria-label="Personal actions"]').exists()).toBe(false)
    expect(itemSection).not.toHaveBeenCalled()

    await wrapper.get('button[data-section="related"]').trigger('click')
    await vi.waitFor(() => expect(wrapper.text()).toContain('Related Movie'))
    expect(itemSection).toHaveBeenCalledWith('movie-1', 'related', expect.any(AbortSignal))

    await wrapper.get('button.play-title').trigger('click')
    expect(wrapper.emitted('play')?.[0]?.[0]).toMatchObject({ Id: 'movie-1' })
    await wrapper.get('button.back-to-library').trigger('click')
    expect(wrapper.emitted('back')).toHaveLength(1)
  })
})
