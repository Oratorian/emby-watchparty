import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/api/client'
import TitleDetails from './TitleDetails.vue'

const series = { Id: 'series-1', Name: 'A Series', Type: 'Series' }
beforeEach(() => {
  vi.spyOn(api, 'itemDetails').mockResolvedValue(series)
  vi.spyOn(api, 'seriesSeasons').mockResolvedValue({ items: [] })
})

describe('series overview previews', () => {
  it('uses an isolated series preview only when the party allows one', async () => {
    const wrapper = mount(TitleDetails, {
      props: { item: series, isHost: false },
      global: { stubs: { ShowBackgroundPreview: true } },
    })
    await flushPromises()
    expect(wrapper.findComponent({ name: 'ShowBackgroundPreview' }).exists()).toBe(false)
    await wrapper.setProps({ previewAllowed: true })
    expect(wrapper.findComponent({ name: 'ShowBackgroundPreview' }).props('seriesId')).toBe('series-1')
    expect(wrapper.get('.detail-hero').classes()).toContain('has-preview')
    await wrapper.setProps({ previewAllowed: false })
    expect(wrapper.findComponent({ name: 'ShowBackgroundPreview' }).exists()).toBe(false)
    wrapper.unmount()
  })

  it('never requests a show preview for a movie', async () => {
    vi.mocked(api.itemDetails).mockResolvedValue({ Id: 'movie-1', Name: 'Movie', Type: 'Movie' })
    const wrapper = mount(TitleDetails, {
      props: { item: { Id: 'movie-1', Name: 'Movie', Type: 'Movie' }, isHost: false, previewAllowed: true },
      global: { stubs: { ShowBackgroundPreview: true } },
    })
    await flushPromises()
    expect(wrapper.findComponent({ name: 'ShowBackgroundPreview' }).exists()).toBe(false)
    expect(wrapper.get('.detail-hero').classes()).not.toContain('has-preview')
    wrapper.unmount()
  })
})
