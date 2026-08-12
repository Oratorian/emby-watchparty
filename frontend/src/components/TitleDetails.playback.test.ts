import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import ToggleSwitch from './ToggleSwitch.vue'
import TitleDetails from './TitleDetails.vue'

/**
 * The playback-options panel, none of which had any coverage.
 *
 * Everything here ends up in the `play` payload, which is what the party acts
 * on for every viewer. The single existing payload assertion is a Movie with
 * one version, no stored position and no binge flag -- so it pins the shape
 * and none of the decisions.
 */

const AUDIO = {
  index: 1, language: 'eng', displayLanguage: 'English AAC',
  codec: 'aac', channels: 2, isDefault: true, title: '',
}
const AUDIO_ALT = { ...AUDIO, index: 5, displayLanguage: 'Commentary AAC' }

function streamsFor(mediaSourceId: string | null) {
  return {
    audio: [mediaSourceId === 'source-2' ? AUDIO_ALT : AUDIO],
    subtitles: [],
    media_source_id: mediaSourceId ?? 'source-1',
    versions: [
      { id: 'source-1', name: 'Theatrical', container: 'mkv', run_time_ticks: 7_200_000_000 },
      { id: 'source-2', name: 'Extended', container: 'mkv', run_time_ticks: 9_000_000_000 },
    ],
  }
}

function mountTitle(details: Record<string, unknown>, isHost = true) {
  vi.spyOn(api, 'itemDetails').mockResolvedValue(details as never)
  return mount(TitleDetails, {
    props: { item: { Id: details.Id, Name: details.Name, Type: details.Type } as never, isHost },
  })
}

async function openPlayback(wrapper: ReturnType<typeof mountTitle>) {
  await wrapper.get('button.play-title').trigger('click')
  await flushPromises()
}

describe('choosing a version', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api, 'qualityOptions').mockResolvedValue({
      options: [{ id: 'auto', label: 'Auto' }], default_id: 'auto',
    } as never)
    vi.spyOn(api, 'itemSection').mockResolvedValue({ section: 'related', items: [] } as never)
  })

  it('refetches the tracks belonging to the version that was picked', async () => {
    const itemStreams = vi.spyOn(api, 'itemStreams').mockImplementation(
      async (_id: string, mediaSourceId?: string) => streamsFor(mediaSourceId ?? null) as never,
    )
    const wrapper = mountTitle({ Id: 'movie-1', Name: 'A Movie', Type: 'Movie' })
    await flushPromises()
    await openPlayback(wrapper)

    // The picker only renders with more than one version, so the existing
    // single-version fixture could never reach any of this.
    const version = wrapper.get('select[aria-label="Version"]')
    await version.setValue('source-2')
    await flushPromises()

    // Track indices are per-version. Keeping the first version's audio list
    // sends an index that means something different, or nothing at all, in
    // the source actually being played.
    expect(itemStreams).toHaveBeenLastCalledWith('movie-1', 'source-2')
    expect(wrapper.get('select[aria-label="Audio"]').text()).toContain('Commentary AAC')

    await wrapper.get('button.start-playback').trigger('click')
    expect(wrapper.emitted('play')?.[0]?.[0]).toMatchObject({
      mediaSourceId: 'source-2',
      audioIndex: 5,
    })
  })
})

describe('resuming a partly watched title', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api, 'qualityOptions').mockResolvedValue({
      options: [{ id: 'auto', label: 'Auto' }], default_id: 'auto',
    } as never)
    vi.spyOn(api, 'itemSection').mockResolvedValue({ section: 'related', items: [] } as never)
    vi.spyOn(api, 'itemStreams').mockResolvedValue(streamsFor('source-1') as never)
  })

  const PARTLY_WATCHED = {
    Id: 'movie-1',
    Name: 'A Movie',
    Type: 'Movie',
    // 100 minutes in, in Emby's 100-nanosecond ticks.
    UserData: { PlaybackPositionTicks: 60_000_000_000, Played: false },
  }

  it('offers to resume, and defaults to it', async () => {
    const wrapper = mountTitle(PARTLY_WATCHED)
    await flushPromises()
    await openPlayback(wrapper)

    const start = wrapper.get('select[aria-label="Start position"]')
    expect((start.element as HTMLSelectElement).value).toBe('resume')
    expect(start.text()).toContain('01:40:00')

    await wrapper.get('button.start-playback').trigger('click')
    expect(wrapper.emitted('play')?.[0]?.[0]).toMatchObject({
      startSeconds: 6000,
      resumeMode: 'resume',
    })
  })

  it('starts from zero when start over is chosen', async () => {
    const wrapper = mountTitle(PARTLY_WATCHED)
    await flushPromises()
    await openPlayback(wrapper)

    await wrapper.get('select[aria-label="Start position"]').setValue('start_over')
    await wrapper.get('button.start-playback').trigger('click')

    expect(wrapper.emitted('play')?.[0]?.[0]).toMatchObject({
      startSeconds: 0,
      resumeMode: 'start_over',
    })
  })

  it('does not offer the control for a title nobody has started', async () => {
    const wrapper = mountTitle({ Id: 'movie-1', Name: 'A Movie', Type: 'Movie' })
    await flushPromises()
    await openPlayback(wrapper)

    expect(wrapper.find('select[aria-label="Start position"]').exists()).toBe(false)
  })
})

describe('arming binge watching from the detail view', () => {
  const EPISODE = { Id: 'ep-1', Name: 'An Episode', Type: 'Episode' }

  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api, 'qualityOptions').mockResolvedValue({
      options: [{ id: 'auto', label: 'Auto' }], default_id: 'auto',
    } as never)
    vi.spyOn(api, 'itemSection').mockResolvedValue({ section: 'related', items: [] } as never)
    vi.spyOn(api, 'itemStreams').mockResolvedValue(streamsFor('source-1') as never)
  })

  it('sends the flag the host actually set', async () => {
    const wrapper = mountTitle(EPISODE, true)
    await flushPromises()
    await openPlayback(wrapper)

    // The redesign replaced a bare checkbox with the app's ToggleSwitch.
    expect(wrapper.findComponent(ToggleSwitch).exists()).toBe(true)

    await wrapper.get('.binge-toggle input[type="checkbox"]').setValue(true)
    await wrapper.get('button.start-playback').trigger('click')

    expect(wrapper.emitted('play')?.[0]?.[0]).toMatchObject({ binge: true })
  })

  it('sends nothing when the host leaves it alone', async () => {
    const wrapper = mountTitle(EPISODE, true)
    await flushPromises()
    await openPlayback(wrapper)

    await wrapper.get('button.start-playback').trigger('click')
    expect(wrapper.emitted('play')?.[0]?.[0]).toMatchObject({ binge: false })
  })

  it('is not offered to a non-host, or on a film', async () => {
    const guest = mountTitle(EPISODE, false)
    await flushPromises()
    await openPlayback(guest)
    expect(guest.find('.binge-toggle').exists()).toBe(false)
    await guest.get('button.start-playback').trigger('click')
    // Undefined, not false: the server distinguishes "no opinion" from "off",
    // and only the host may hold an opinion.
    expect(guest.emitted('play')?.[0]?.[0]).toMatchObject({ binge: undefined })

    vi.restoreAllMocks()
    vi.spyOn(api, 'qualityOptions').mockResolvedValue({
      options: [{ id: 'auto', label: 'Auto' }], default_id: 'auto',
    } as never)
    vi.spyOn(api, 'itemSection').mockResolvedValue({ section: 'related', items: [] } as never)
    vi.spyOn(api, 'itemStreams').mockResolvedValue(streamsFor('source-1') as never)
    const film = mountTitle({ Id: 'movie-1', Name: 'A Movie', Type: 'Movie' }, true)
    await flushPromises()
    await openPlayback(film)
    expect(film.find('.binge-toggle').exists()).toBe(false)
  })
})

describe('adding a title to a playlist', () => {
  const MOVIE = { Id: 'movie-1', Name: 'A Movie', Type: 'Movie' }

  beforeEach(() => {
    vi.restoreAllMocks()
    vi.spyOn(api, 'qualityOptions').mockResolvedValue({
      options: [{ id: 'auto', label: 'Auto' }], default_id: 'auto',
    } as never)
    vi.spyOn(api, 'itemSection').mockResolvedValue({ section: 'related', items: [] } as never)
    vi.spyOn(api, 'playlists').mockResolvedValue({
      items: [{ Id: 'playlist-1', Name: 'Saturday Night', Type: 'Playlist' }],
    } as never)
  })

  async function openPicker() {
    const wrapper = mountTitle(MOVIE, true)
    await flushPromises()
    const open = wrapper.findAll('button').find((button) => button.text() === 'Add to playlist')
    expect(open, 'the host has no way to reach the playlist picker').toBeTruthy()
    await open!.trigger('click')
    await flushPromises()
    return wrapper
  }

  it('posts the playlist and the item the right way round', async () => {
    const addPlaylistItem = vi.spyOn(api, 'addPlaylistItem').mockResolvedValue({} as never)
    const wrapper = await openPicker()

    const add = wrapper.findAll('.playlist-picker button')[0]!
    // Nothing chosen yet, so there is nothing to add to.
    expect((add.element as HTMLButtonElement).disabled).toBe(true)

    await wrapper.get('select[aria-label="Playlist"]').setValue('playlist-1')
    await add.trigger('click')
    await flushPromises()

    // Swapped, every add writes to a playlist named after the item -- a 404 at
    // best, the wrong playlist at worst. Argument order is the whole test.
    expect(addPlaylistItem).toHaveBeenCalledWith('playlist-1', 'movie-1')
    expect(wrapper.find('.playlist-picker').exists()).toBe(false)
  })

  it('creates a playlist and adds to the one it just created', async () => {
    const createPlaylist = vi.spyOn(api, 'createPlaylist')
      .mockResolvedValue({ id: 'playlist-new' } as never)
    const addPlaylistItem = vi.spyOn(api, 'addPlaylistItem').mockResolvedValue({} as never)
    const wrapper = await openPicker()

    await wrapper.get('input[aria-label="New playlist name"]').setValue('Fresh')
    await wrapper.findAll('.playlist-picker button')[1]!.trigger('click')
    await flushPromises()

    expect(createPlaylist).toHaveBeenCalledWith('Fresh')
    expect(addPlaylistItem).toHaveBeenCalledWith('playlist-new', 'movie-1')
    expect(wrapper.find('.playlist-picker').exists()).toBe(false)
  })

  it('reports a failure inline instead of closing as if it worked', async () => {
    vi.spyOn(api, 'addPlaylistItem').mockRejectedValue(new Error('Emby rejected the add'))
    const wrapper = await openPicker()

    await wrapper.get('select[aria-label="Playlist"]').setValue('playlist-1')
    await wrapper.findAll('.playlist-picker button')[0]!.trigger('click')
    await flushPromises()

    expect(wrapper.get('.inline-error').text()).toContain('Emby rejected the add')
    expect(wrapper.find('.playlist-picker').exists()).toBe(true)
  })
})
