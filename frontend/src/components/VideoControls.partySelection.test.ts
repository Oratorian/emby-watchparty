import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import VideoControls from './VideoControls.vue'

const STREAMS = {
  media_source_id: 'source-1',
  versions: [{ id: 'source-1', name: 'Fake Source' }],
  audio: [
    { index: 1, label: 'English AAC', isDefault: true },
    { index: 2, label: 'Spanish AAC', isDefault: false },
  ],
  subtitles: [
    { index: 3, label: 'English SRT', isDefault: true, isTextSubtitle: true },
    { index: 4, label: 'Forced', isDefault: false, isTextSubtitle: true },
  ],
}

function mountControls(overrides: Record<string, unknown> = {}) {
  return mount(VideoControls, {
    props: {
      partyId: 'ABC12',
      itemId: 'movie-1',
      streamUrl: '/hls/movie-1.m3u8',
      quality: '1080p-high',
      currentTime: 0,
      mediaSourceId: 'source-1',
      ...overrides,
    },
    global: { plugins: [createPinia()] },
  })
}

describe('VideoControls and the party-wide track selection', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
    vi.spyOn(api, 'itemStreams').mockResolvedValue(STREAMS as never)
    vi.spyOn(api, 'qualityOptions').mockResolvedValue({
      options: [{ id: '1080p-high', label: '1080p' }],
      default_id: '1080p-high',
    } as never)
  })

  it('keeps the audio track the party selected instead of the source default', async () => {
    // The detail view can set a non-default track for everyone. This strip had
    // no audioIndex prop at all and reseeded from IsDefault, so it displayed
    // the wrong language and re-emitted change_streams with the stale index,
    // reverting the party's choice for this viewer.
    const wrapper = mountControls({ audioIndex: 2 })
    await flushPromises()

    expect((wrapper.vm as unknown as { selectedAudio: number }).selectedAudio).toBe(2)
  })

  it('falls back to the source default only when the party has no selection', async () => {
    const wrapper = mountControls({ audioIndex: null })
    await flushPromises()

    expect((wrapper.vm as unknown as { selectedAudio: number }).selectedAudio).toBe(1)
  })

  it('keeps a party selection of "subtitles off" rather than re-enabling the default', async () => {
    // -1 is a real choice, not an absent one. Treating it as absent turned
    // subtitles back on for every viewer whose controls refetched.
    const wrapper = mountControls({ subtitleIndex: -1 })
    await flushPromises()

    expect((wrapper.vm as unknown as { selectedSubtitle: number }).selectedSubtitle).toBe(-1)
  })

  it('ignores a party selection the current source does not contain', async () => {
    // Switching versions can drop a track. Seeding an index that no longer
    // exists would send Emby an invalid stream index.
    const wrapper = mountControls({ audioIndex: 99 })
    await flushPromises()

    expect((wrapper.vm as unknown as { selectedAudio: number }).selectedAudio).toBe(1)
  })
})
