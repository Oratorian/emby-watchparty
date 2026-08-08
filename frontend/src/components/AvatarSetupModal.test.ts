import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import { useAvatarStore } from '@/stores/avatar'
import AvatarSetupModal from './AvatarSetupModal.vue'

describe('avatar recovery failures', () => {
  it('shows the backend rate-limit detail inline', async () => {
    const pinia = createPinia()
    setActivePinia(pinia)
    vi.spyOn(useAvatarStore(), 'recover').mockRejectedValue(new ApiError(
      429,
      'Too many avatar recovery attempts. Try again in 90 seconds.',
      { code: 'rate_limited', retry_after: 90 },
      'rate_limited',
      90,
    ))
    const wrapper = mount(AvatarSetupModal, { global: { plugins: [pinia] } })

    await wrapper.get('.tabs button:nth-child(3)').trigger('click')
    await wrapper.get('input[placeholder="word-word-word"]').setValue('able-acid-aged')
    await wrapper.get('.tab-body button').trigger('click')
    await flushPromises()

    expect(wrapper.get('.error').text()).toBe(
      'Too many avatar recovery attempts. Try again in 90 seconds.',
    )
  })
})
