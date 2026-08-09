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
    vi.spyOn(api, 'itemStreams').mockResolvedValue({
      audio: [{ index: 1, language: 'eng', displayLanguage: 'English', codec: 'aac', channels: 2, isDefault: true, title: 'English' }],
      subtitles: [{ index: 2, language: 'eng', displayLanguage: 'English', codec: 'subrip', isDefault: false, isForced: false, isExternal: true, isPGS: false, isTextSubtitleStream: true, title: 'English' }],
      media_source_id: 'source-1',
      versions: [{ id: 'source-1', name: '1080p', container: 'mkv', run_time_ticks: 7_200_000_000 }],
    })
    vi.spyOn(api, 'qualityOptions').mockResolvedValue({
      options: [{ id: 'auto', label: 'Auto', resolution: null, width: null, height: null, bitrate_kbps: null }],
      default_id: 'auto',
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
    await vi.waitFor(() => expect(wrapper.text()).toContain('Start watch party'))
    await wrapper.get('button.start-playback').trigger('click')
    expect(wrapper.emitted('play')?.[0]?.[0]).toMatchObject({
      item: { Id: 'movie-1' },
      mediaSourceId: 'source-1',
      quality: 'auto',
      audioIndex: 1,
      subtitleIndex: -1,
      resumeMode: 'start_over',
    })
    await wrapper.get('button.back-to-library').trigger('click')
    expect(wrapper.emitted('back')).toHaveLength(1)
  })

  it('optimistically updates host state, locks duplicates, and rolls back inline', async () => {
    vi.spyOn(api, 'itemDetails').mockResolvedValue({
      Id: 'movie-1',
      Name: 'Artifact Movie',
      Type: 'Movie',
      UserData: { IsFavorite: false, Played: false },
    })
    let rejectFavorite!: (reason: Error) => void
    const setFavorite = vi.spyOn(api, 'setFavorite').mockReturnValue(new Promise((_, reject) => {
      rejectFavorite = reject
    }))
    const wrapper = mount(TitleDetails, {
      props: {
        item: { Id: 'movie-1', Name: 'Artifact Movie', Type: 'Movie' },
        isHost: true,
      },
    })
    await vi.waitFor(() => expect(wrapper.text()).toContain('Favorite'))

    const favorite = wrapper.get('button.favorite-action')
    await favorite.trigger('click')
    expect(favorite.text()).toContain('Remove favorite')
    expect((favorite.element as HTMLButtonElement).disabled).toBe(true)
    await favorite.trigger('click')
    expect(setFavorite).toHaveBeenCalledTimes(1)

    rejectFavorite(new Error('Emby rejected favorite'))
    await vi.waitFor(() => expect(wrapper.text()).toContain('Emby rejected favorite'))
    expect(favorite.text()).toBe('Favorite')
    expect((favorite.element as HTMLButtonElement).disabled).toBe(false)
  })
})
