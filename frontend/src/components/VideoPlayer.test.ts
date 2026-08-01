import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import VideoPlayer from './VideoPlayer.vue'

vi.mock('hls.js', () => ({
  default: class FakeHls {
    static isSupported() {
      return false
    }
  },
}))

describe('VideoPlayer native HLS support', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.spyOn(HTMLMediaElement.prototype, 'canPlayType').mockReturnValue('probably')
    vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {})
  })

  it('reports iOS autoplay blocking through the public component event', async () => {
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockRejectedValue(
      new DOMException('User gesture required', 'NotAllowedError'),
    )

    const wrapper = mount(VideoPlayer, {
      props: {
        streamUrl: '/hls/native/master.m3u8',
        title: 'Movie',
        playing: true,
      },
    })

    await wrapper.get('video').trigger('loadedmetadata')
    await Promise.resolve()

    expect(wrapper.emitted('autoplay-blocked')).toHaveLength(1)
    wrapper.unmount()
  })

  it('releases the native HLS request when the player unmounts', () => {
    const wrapper = mount(VideoPlayer, {
      props: {
        streamUrl: '/hls/native/master.m3u8',
        title: 'Movie',
        playing: false,
      },
    })
    const video = wrapper.get('video').element as HTMLVideoElement
    expect(video.getAttribute('src')).toBe('/hls/native/master.m3u8')

    wrapper.unmount()

    expect(video.getAttribute('src')).toBeNull()
    expect(video.load).toHaveBeenCalledOnce()
  })
})
