import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'

import { i18n } from '@/i18n'
import LibraryFilters from './LibraryFilters.vue'

afterEach(() => {
  i18n.global.locale.value = 'en'
})

describe('localized library filters', () => {
  it('switches rendered provider labels and preserves filter request IDs and values', async () => {
    i18n.global.locale.value = 'en'
    const wrapper = mount(LibraryFilters, {
      props: {
        controls: [{
          id: 'playstate', label: 'Playstate', kind: 'select',
          values: [
            { value: 'any', label: 'Any' },
            { value: 'unplayed', label: 'Unplayed' },
            { value: 'played', label: 'Played' },
          ],
        }],
        modelValue: { playstate: 'played' },
      },
    })
    await wrapper.get('.filter-toggle').trigger('click')
    expect(wrapper.get('select').attributes('aria-label')).toBe('Playstate')

    i18n.global.locale.value = 'de'
    await nextTick()
    expect(wrapper.get('select').attributes('aria-label')).toBe('Wiedergabestatus')
    expect(wrapper.get('option[value="unplayed"]').text()).toBe('Ungesehen')
    expect(wrapper.get('.filter-chip').text()).toBe('Wiedergabestatus: Gesehen')

    await wrapper.get('select').setValue('unplayed')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([{ playstate: 'unplayed' }])
    wrapper.unmount()
  })

  it('translates static video types while preserving catalog content and future provider labels', async () => {
    i18n.global.locale.value = 'de'
    const wrapper = mount(LibraryFilters, {
      props: {
        controls: [
          { id: 'video_type', label: 'Video type', kind: 'multi', values: [{ value: 'VideoFile', label: 'VideoFile' }] },
          { id: 'genre', label: 'Genre', kind: 'multi', values: [{ value: 'With', label: 'With' }] },
          { id: 'future_filter', label: 'Provider custom label', kind: 'multi', values: [{ value: 'any', label: 'Custom option' }] },
        ],
        modelValue: {},
      },
    })
    await wrapper.get('.filter-toggle').trigger('click')
    await wrapper.get('.advanced-toggle').trigger('click')
    await wrapper.get('[data-filter-id="video_type"] button').trigger('click')
    expect(wrapper.get('[data-filter-id="video_type"] .option-list').text()).toBe('Videodatei')
    await wrapper.get('input[value="VideoFile"]').setValue(true)
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([{ video_type: ['VideoFile'] }])

    await wrapper.get('[data-filter-id="genre"] button').trigger('click')
    expect(wrapper.get('[data-filter-id="genre"] .option-list').text()).toBe('With')
    await wrapper.get('[data-filter-id="future_filter"] button').trigger('click')
    expect(wrapper.get('[data-filter-id="future_filter"]').text()).toContain('Provider custom label')
    expect(wrapper.get('[data-filter-id="future_filter"] .option-list').text()).toBe('Custom option')
    wrapper.unmount()
  })

  it('updates year-mode choices when the language changes with the year picker open', async () => {
    i18n.global.locale.value = 'en'
    const wrapper = mount(LibraryFilters, {
      props: { controls: [{ id: 'year', label: 'Year', kind: 'multi', values: [] }], modelValue: {} },
    })
    await wrapper.get('.filter-toggle').trigger('click')
    await wrapper.get('[data-filter-id="year"] > .filter-multi > button').trigger('click')
    expect(wrapper.get('.year-modes button').text()).toBe('Exact')
    i18n.global.locale.value = 'de'
    await nextTick()
    expect(wrapper.get('.year-modes button').text()).toBe('Genau')
    expect(wrapper.get('input[type="number"]').attributes('aria-label')).toBe('Genaues Jahr')
    wrapper.unmount()
  })
})
