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

describe('pre-playback subtitle choice', () => {
  function subtitleStreams(): StreamsResponse {
    return {
      audio: [],
      subtitles: [
        {
          index: 2,
          language: 'eng',
          displayLanguage: 'English',
          codec: 'ass',
          isDefault: true,
          isForced: false,
          isExternal: false,
          isTextSubtitleStream: true,
          isPGS: false,
          title: 'Dialogue',
        },
      ],
      media_source_id: 'source-a',
      versions: [],
    } as unknown as StreamsResponse
  }

  // jsdom does not implement HTMLTrackElement.track, so track.mode is not
  // observable here. The composable only arms a 'loadeddata' handler to show a
  // track when it has decided there is one to show, so that registration is a
  // faithful stand-in for the decision under test.
  async function decidedToShowATrack(subtitleIndex: number | null) {
    vi.spyOn(api, 'itemStreams').mockResolvedValue(subtitleStreams())
    const party = reactive<{
      partyId: string | null
      currentVideo: Record<string, unknown> | null
      myStreamUrl: string | null
    }>({ partyId: 'PARTY', currentVideo: null, myStreamUrl: null })
    let video: HTMLVideoElement | null = null

    const wrapper = mount(defineComponent({
      setup() {
        usePartyStream({ emit: vi.fn() } as never, party as never, vi.fn(), () => video)
        return () => h('video', { ref: (el: unknown) => { video = el as HTMLVideoElement } })
      },
    }))

    const listened: string[] = []
    const element = video as unknown as HTMLVideoElement
    const realAdd = element.addEventListener.bind(element)
    element.addEventListener = ((
      type: string,
      listener: EventListenerOrEventListenerObject,
      options?: boolean | AddEventListenerOptions,
    ) => {
      listened.push(type)
      realAdd(type, listener, options)
    }) as HTMLVideoElement['addEventListener']

    party.currentVideo = {
      item_id: 'item-1',
      media_source_id: 'source-a',
      subtitle_index: subtitleIndex,
    }
    party.myStreamUrl = '/hls/item-1/master.m3u8'
    await nextTick()
    await flushPromises()
    await nextTick()

    const trackCount = (video as unknown as HTMLVideoElement).querySelectorAll('track').length
    wrapper.unmount()
    return { showed: listened.includes('loadeddata'), trackCount }
  }

  it('shows nothing when the selector chose Off', async () => {
    // -1 is a decision, not a failed lookup. No subtitle stream carries index
    // -1, so passing it through find() returns undefined and the source's
    // isDefault track was substituted: picking Off started the episode with
    // subtitles on screen and the CC control showing track one as active.
    const { showed, trackCount } = await decidedToShowATrack(-1)

    expect(showed).toBe(false)
    // The tracks are still preloaded, so the in-player strip can switch to one
    // later. They are simply not displayed.
    expect(trackCount).toBe(1)
  })

  it('still falls back to the source default when nothing was chosen', async () => {
    // The Off fix must not break the ordinary case: no choice at all should
    // still honour the file's own default track.
    const { showed } = await decidedToShowATrack(null)

    expect(showed).toBe(true)
  })

  it('honours an explicitly chosen track', async () => {
    const { showed } = await decidedToShowATrack(2)

    expect(showed).toBe(true)
  })
})
