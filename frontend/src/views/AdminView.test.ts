import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { describe, expect, it, vi } from 'vitest'

import { ApiError, type AdminConfig, api } from '@/api/client'
import AdminView from './AdminView.vue'

describe('admin login failures', () => {
  it('shows the backend rate-limit detail inline', async () => {
    vi.spyOn(api, 'adminGetConfig').mockResolvedValue({ error: 'Not authenticated' } as AdminConfig)
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
    await flushPromises()

    const inputs = wrapper.findAll('input')
    await inputs[0]!.setValue('Alice')
    await inputs[1]!.setValue('password')
    await wrapper.get('form').trigger('submit')
    await flushPromises()

    expect(wrapper.get('.error-msg').text()).toBe(
      'Too many login attempts. Try again in 30 seconds.',
    )
    wrapper.unmount()
  })

  it('offers Retry for a failed initial probe and shows login only after a confirmed refusal', async () => {
    vi.spyOn(api, 'adminGetConfig')
      .mockRejectedValueOnce(new ApiError(503, 'Service unavailable', undefined))
      .mockResolvedValue({ error: 'Not authenticated' } as AdminConfig)
    const wrapper = mount(AdminView, {
      global: { plugins: [createPinia()], stubs: { RouterLink: true } },
    })
    await flushPromises()

    expect(wrapper.find('.login-page').exists()).toBe(false)
    expect(wrapper.get('[role="alert"]').text()).toContain('Service unavailable')

    await wrapper.get('[role="alert"] button').trigger('click')
    await flushPromises()

    expect(wrapper.find('.login-page').exists()).toBe(true)
    expect(wrapper.find('.admin-panel-body').exists()).toBe(false)
    wrapper.unmount()
  })
})
