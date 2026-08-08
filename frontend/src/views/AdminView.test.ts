import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { describe, expect, it, vi } from 'vitest'

import { ApiError, api } from '@/api/client'
import AdminView from './AdminView.vue'

describe('admin login failures', () => {
  it('shows the backend rate-limit detail inline', async () => {
    vi.spyOn(api, 'adminGetConfig').mockRejectedValue(new Error('Not authenticated'))
    vi.spyOn(api, 'adminLogin').mockRejectedValue(new ApiError(
      429,
      'Too many login attempts. Try again in 30 seconds.',
      { code: 'rate_limited', retry_after: 30 },
      'rate_limited',
      30,
    ))
    const wrapper = mount(AdminView, {
      global: { plugins: [createPinia()], stubs: { RouterLink: true } },
    })

    const inputs = wrapper.findAll('input')
    await inputs[0]!.setValue('Alice')
    await inputs[1]!.setValue('password')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.get('.error-msg').text()).toBe(
      'Too many login attempts. Try again in 30 seconds.',
    )
  })
})
