import { defineComponent, h, nextTick, reactive } from 'vue'
import { flushPromises, mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import type { StreamsResponse } from '@/api/client'
import { usePartyStream } from './usePartyStream'

describe('usePartyStream', () => {
  it('preloads subtitles from selected media version', async () => {
    const itemStreams = vi.spyOn(api, 'itemStreams').mockResolvedValue({
      audio: [],
      subtitles: [],
      media_source_id: 'source-b',
      versions: [],
    })
    const party = reactive<{
      partyId: string | null
      currentVideo: { item_id: string; media_source_id: string } | null
      myStreamUrl: string | null
    }>({
      partyId: 'PARTY',
      currentVideo: null,
      myStreamUrl: null,
    })
    const socket = { emit: vi.fn() }
    let video: HTMLVideoElement | null = null

    const wrapper = mount(defineComponent({
      setup() {
        usePartyStream(
          socket as never,
          party as never,
          vi.fn(),
          () => video,
        )
        return () => h('video', { ref: (element: unknown) => { video = element as HTMLVideoElement } })
      },
    }))

    party.currentVideo = {
      item_id: 'item-1',
      media_source_id: 'source-b',
    }
    party.myStreamUrl = '/hls/item-1/master.m3u8'
    await nextTick()
    await vi.waitFor(() => {
      expect(itemStreams).toHaveBeenCalledWith(
        'item-1',
        'source-b',
        expect.any(AbortSignal),
      )
    })

    wrapper.unmount()
  })

  it('does not duplicate a subtitle selected while preload is pending', async () => {
    let resolveStreams!: (streams: StreamsResponse) => void
    vi.spyOn(api, 'itemStreams').mockReturnValue(new Promise((resolve) => {
      resolveStreams = resolve
    }))
    const party = reactive<{
      partyId: string | null
      currentVideo: { item_id: string; media_source_id: string } | null
      myStreamUrl: string | null
    }>({
      partyId: 'PARTY',
      currentVideo: null,
      myStreamUrl: null,
    })
    let video: HTMLVideoElement | null = null
    let stream!: ReturnType<typeof usePartyStream>

    const wrapper = mount(defineComponent({
      setup() {
        stream = usePartyStream(
          { emit: vi.fn() } as never,
          party as never,
          vi.fn(),
          () => video,
        )
        return () => h('video', { ref: (element: unknown) => { video = element as HTMLVideoElement } })
      },
    }))

    party.currentVideo = { item_id: 'item-1', media_source_id: 'source-b' }
    party.myStreamUrl = '/hls/item-1/master.m3u8'
    await nextTick()
    await vi.waitFor(() => expect(api.itemStreams).toHaveBeenCalled())

    stream.changeTextSubtitle({
      index: 3,
      url: '/api/subtitles/item-1/source-b/3',
    })
    expect(wrapper.findAll('track')).toHaveLength(1)

    resolveStreams({
      audio: [],
      subtitles: [{
        index: 3,
        language: 'eng',
        displayLanguage: 'English',
        codec: 'subrip',
        isDefault: false,
        isForced: false,
        isExternal: true,
        isPGS: false,
        isTextSubtitleStream: true,
        title: 'English',
      }],
      media_source_id: 'source-b',
      versions: [],
    })

    // Drained rather than polled. vi.waitFor runs its callback once,
    // synchronously, before the resolved itemStreams continuation gets to
    // run -- so it was observing the DOM as it stood BEFORE the preload
    // finished and could not have seen a duplicate however many appeared.
    await flushPromises()

    // Identity, not just the count: the surviving track has to be the one the
    // user picked, not the preload's own copy of the same subtitle.
    const sources = wrapper.findAll('track')
      .map((track) => (track.element as HTMLTrackElement).getAttribute('src'))
    expect(sources).toEqual(['/api/v2/items/item-1/subtitles/source-b/3'])
    wrapper.unmount()
  })
})
