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

  it('shows every option in large catalogs and keeps them searchable', async () => {
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
    expect(wrapper.findAll('input[type="checkbox"]')).toHaveLength(30)
    expect(wrapper.text()).not.toContain('more options')

    await wrapper.get('input[aria-label="Search Genre options"]').setValue('Drama')
    expect(wrapper.findAll('input[type="checkbox"]')).toHaveLength(1)
    expect(wrapper.text()).toContain('Drama')
  })

  it('closes an option popover when clicking outside its filter control', async () => {
    const wrapper = mount(LibraryFilters, {
      attachTo: document.body,
      props: {
        controls: [{
          id: 'genre', label: 'Genre', kind: 'multi',
          values: [{ value: 'Drama', label: 'Drama' }],
        }],
        modelValue: {},
      },
    })

    await wrapper.get('button.filter-toggle').trigger('click')
    await wrapper.get('button[aria-label="Open Genre filter"]').trigger('click')
    expect(wrapper.find('.option-popover').exists()).toBe(true)

    document.body.click()
    await wrapper.vm.$nextTick()

    expect(wrapper.find('.option-popover').exists()).toBe(false)
    wrapper.unmount()
  })

  it('applies exact, range, and decade year modes only after confirmation', async () => {
    const wrapper = mount(LibraryFilters, {
      props: {
        controls: [{
          id: 'year', label: 'Year', kind: 'multi',
          values: [{ value: '2026', label: '2026' }, { value: '1888', label: '1888' }],
        }],
        modelValue: {},
      },
    })

    await wrapper.get('button.filter-toggle').trigger('click')
    await wrapper.get('button[aria-label="Open Year filter"]').trigger('click')
    await wrapper.get('input[aria-label="Exact year"]').setValue('2014')
    expect(wrapper.emitted('update:modelValue')).toBeUndefined()
    await wrapper.get('button[aria-label="Apply year filter"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([{ year: 'exact:2014' }])

    await wrapper.get('button[aria-label="Year range mode"]').trigger('click')
    await wrapper.get('input[aria-label="Start year"]').setValue('2014')
    await wrapper.get('input[aria-label="End year"]').setValue('2021')
    await wrapper.get('button[aria-label="Apply year filter"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([{ year: 'range:2014:2021' }])

    await wrapper.get('button[aria-label="Decade mode"]').trigger('click')
    await wrapper.get('select[aria-label="Year decade"]').setValue('2000')
    await wrapper.get('button[aria-label="Apply year filter"]').trigger('click')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([{ year: 'decade:2000' }])
    expect(wrapper.get('.filter-chip').text()).toBe('Year: 2000–2009')
  })
})
