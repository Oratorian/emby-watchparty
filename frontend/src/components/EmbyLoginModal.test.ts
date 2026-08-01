import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'

import EmbyLoginModal from './EmbyLoginModal.vue'

describe('EmbyLoginModal accessibility', () => {
  afterEach(() => {
    document.body.innerHTML = ''
  })

  it('traps focus, closes with Escape, and restores trigger focus', async () => {
    const trigger = document.createElement('button')
    document.body.append(trigger)
    trigger.focus()
    const wrapper = mount(EmbyLoginModal, { attachTo: document.body })
    await nextTick()

    const username = wrapper.get('input[type="text"]').element as HTMLInputElement
    const submit = wrapper.get('button[type="submit"]').element as HTMLButtonElement
    expect(document.activeElement).toBe(username)

    username.focus()
    await wrapper.trigger('keydown', { key: 'Tab', shiftKey: true })
    expect(document.activeElement).toBe(submit)

    await wrapper.trigger('keydown', { key: 'Escape' })
    expect(wrapper.emitted('cancel')).toHaveLength(1)
    wrapper.unmount()
    expect(document.activeElement).toBe(trigger)
  })
})
