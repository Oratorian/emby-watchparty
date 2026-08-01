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
})
