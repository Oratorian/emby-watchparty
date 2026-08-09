import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import LibraryFilters from './LibraryFilters.vue'

describe('LibraryFilters', () => {
  it('shows a readable Any choice for select controls with no upstream default', async () => {
    const wrapper = mount(LibraryFilters, {
      props: {
        controls: [{
          id: 'resolution',
          label: 'Resolution',
          kind: 'select',
          values: [{ value: '4k', label: '4K' }],
        }],
        modelValue: {},
      },
    })

    await wrapper.get('button[aria-expanded="false"]').trigger('click')

    const options = wrapper.get('select[aria-label="Resolution"]').findAll('option')
    expect(options.map((option) => option.text())).toEqual(['Any', '4K'])
    expect((wrapper.get('select[aria-label="Resolution"]').element as HTMLSelectElement).value).toBe('')
  })

  it('applies available controls immediately and resets active filters', async () => {
    const wrapper = mount(LibraryFilters, {
      props: {
        controls: [
          {
            id: 'playstate',
            label: 'Playstate',
            kind: 'select',
            values: [
              { value: 'any', label: 'Any' },
              { value: 'unplayed', label: 'Unplayed' },
            ],
          },
          {
            id: 'genre',
            label: 'Genre',
            kind: 'multi',
            values: [{ value: 'Drama', label: 'Drama' }],
          },
        ],
        modelValue: {},
      },
    })

    await wrapper.get('button[aria-expanded="false"]').trigger('click')
    await wrapper.get('select[aria-label="Playstate"]').setValue('unplayed')
    await wrapper.get('input[value="Drama"]').setValue(true)

    expect(wrapper.text()).toContain('2 active')
    expect(wrapper.text()).toContain('Playstate: Unplayed')
    expect(wrapper.text()).toContain('Genre: Drama')
    expect(wrapper.emitted('update:modelValue')?.at(-1)?.[0]).toEqual({
      playstate: 'unplayed',
      genre: ['Drama'],
    })

    await wrapper.get('button.reset-all').trigger('click')
    expect(wrapper.emitted('update:modelValue')?.at(-1)?.[0]).toEqual({})
  })
})
