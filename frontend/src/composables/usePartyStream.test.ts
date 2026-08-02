import { defineComponent, h, nextTick, reactive } from 'vue'
import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
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
})
