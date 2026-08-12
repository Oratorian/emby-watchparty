import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import LibraryFilters from './LibraryFilters.vue'

describe('LibraryFilters', () => {
  it('shows Any instead of a blank value for inactive select filters', async () => {
    const wrapper = mount(LibraryFilters, {
      props: {
        controls: [{
          id: 'resolution', label: 'Resolution', kind: 'select',
          values: [{ value: 'any', label: 'Any' }, { value: '4K', label: '4K' }],
        }],
        modelValue: {},
      },
    })

    await wrapper.get('button.filter-toggle').trigger('click')

    expect((wrapper.get('select[aria-label="Resolution"]').element as HTMLSelectElement).value).toBe('any')
  })

  it('keeps common filters visible and tucks advanced filters behind a disclosure', async () => {
    const wrapper = mount(LibraryFilters, {
      props: {
        controls: [
          {
            id: 'playstate', label: 'Playstate', kind: 'select',
            values: [{ value: 'any', label: 'Any' }, { value: 'unplayed', label: 'Unplayed' }],
          },
          {
            id: 'genre', label: 'Genre', kind: 'multi',
            values: [{ value: 'Drama', label: 'Drama' }],
          },
          {
            id: 'studio', label: 'Studio', kind: 'multi',
            values: [{ value: 'A24', label: 'A24' }],
          },
        ],
        modelValue: { studio: ['A24'] },
      },
    })

    await wrapper.get('button.filter-toggle').trigger('click')

    expect(wrapper.find('button[aria-label="Open Genre filter"]').exists()).toBe(true)
    expect(wrapper.find('button[aria-label="Open Studio filter"]').exists()).toBe(false)
    expect(wrapper.get('button.advanced-toggle').text()).toContain('1 active')

    await wrapper.get('button.advanced-toggle').trigger('click')
    expect(wrapper.find('button[aria-label="Open Studio filter"]').exists()).toBe(true)
  })

  it('keeps large option catalogs compact and searchable', async () => {
    const genres = Array.from({ length: 30 }, (_, index) => ({
      value: index === 20 ? 'Drama' : `Genre ${index + 1}`,
      label: index === 20 ? 'Drama' : `Genre ${index + 1}`,
    }))
    const wrapper = mount(LibraryFilters, {
      props: {
        controls: [{ id: 'genre', label: 'Genre', kind: 'multi', values: genres }],
        modelValue: {},
      },
    })

    await wrapper.get('button.filter-toggle').trigger('click')
    expect(wrapper.findAll('input[type="checkbox"]')).toHaveLength(0)

    await wrapper.get('button[aria-label="Open Genre filter"]').trigger('click')
    expect(wrapper.findAll('input[type="checkbox"]')).toHaveLength(8)
    expect(wrapper.text()).toContain('22 more options')

    await wrapper.get('input[aria-label="Search Genre options"]').setValue('Drama')
    expect(wrapper.findAll('input[type="checkbox"]')).toHaveLength(1)
    expect(wrapper.text()).toContain('Drama')
  })
})
