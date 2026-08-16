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

    const usernameWrapper = wrapper.get('input[type="text"]')
    const username = usernameWrapper.element as HTMLInputElement
    const submitWrapper = wrapper.get('button[type="submit"]')
    const submit = submitWrapper.element as HTMLButtonElement
    expect(document.activeElement).toBe(username)

    await usernameWrapper.trigger('keydown', { key: 'Escape' })
    expect(wrapper.emitted('cancel')).toHaveLength(1)

    submit.focus()
    await submitWrapper.trigger('keydown', { key: 'Tab' })
    expect(document.activeElement).toBe(username)

    wrapper.unmount()
    expect(document.activeElement).toBe(trigger)
  })

  it('uses the selected media server name in default login copy', () => {
    const wrapper = mount(EmbyLoginModal, { props: { providerName: 'Jellyfin' } })

    expect(wrapper.get('h2').text()).toBe('Jellyfin Login')
    expect(wrapper.get('input[type="text"]').attributes('placeholder')).toBe('Jellyfin username')
    expect(wrapper.get('input[type="password"]').attributes('placeholder')).toBe(
      'Jellyfin password',
    )
  })
})
