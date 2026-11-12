import { flushPromises, mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api } from '@/api/client'
import TitleDetails from './TitleDetails.vue'

const series = { Id: 'series-1', Name: 'A Series', Type: 'Series' }
beforeEach(() => {
  vi.spyOn(api, 'itemDetails').mockResolvedValue(series)
  vi.spyOn(api, 'seriesSeasons').mockResolvedValue({ items: [] })
})

describe('overview background previews', () => {
  it.each([
    series,
    { Id: 'movie-1', Name: 'A Movie', Type: 'Movie' },
  ])('uses an isolated $Type preview only when the party allows one', async (item) => {
    vi.mocked(api.itemDetails).mockResolvedValue(item)
    const wrapper = mount(TitleDetails, {
      props: { item, isHost: false },
      global: { stubs: { ShowBackgroundPreview: true } },
    })
    await flushPromises()
    expect(wrapper.findComponent({ name: 'ShowBackgroundPreview' }).exists()).toBe(false)
    await wrapper.setProps({ previewAllowed: true })
    expect(wrapper.findComponent({ name: 'ShowBackgroundPreview' }).props('itemId')).toBe(item.Id)
    expect(wrapper.get('.detail-hero').classes()).toContain('has-preview')
    await wrapper.setProps({ previewAllowed: false })
    expect(wrapper.findComponent({ name: 'ShowBackgroundPreview' }).exists()).toBe(false)
    wrapper.unmount()
  })

  it.each(['Episode', 'Season', 'BoxSet', 'Video'])(
    'does not request a background preview for a %s', async (type) => {
      const item = { Id: 'other-1', Name: 'Other title', Type: type }
      vi.mocked(api.itemDetails).mockResolvedValue(item)
      const wrapper = mount(TitleDetails, {
        props: { item, isHost: false, previewAllowed: true },
        global: { stubs: { ShowBackgroundPreview: true } },
      })
      await flushPromises()
      expect(wrapper.findComponent({ name: 'ShowBackgroundPreview' }).exists()).toBe(false)
      expect(wrapper.get('.detail-hero').classes()).not.toContain('has-preview')
      wrapper.unmount()
    },
  )
})
