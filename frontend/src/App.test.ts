import { mount, flushPromises } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import App from './App.vue'
import { api } from '@/api/client'
import type { AuthResponse } from '@/api/client'

vi.mock('@/api/client', () => ({
  api: {
    authStatus: vi.fn(),
  },
}))

describe('application startup', () => {
  beforeEach(() => {
    vi.mocked(api.authStatus).mockReset()
  })

  it('keeps routed content hidden until Vue finishes startup', async () => {
    let finishStartup!: (value: AuthResponse) => void
    vi.mocked(api.authStatus).mockReturnValue(
      new Promise((resolve) => {
        finishStartup = resolve
      }),
    )

    const wrapper = mount(App, {
      global: {
        plugins: [createPinia()],
        stubs: { RouterView: { template: '<div data-testid="route">route</div>' } },
      },
    })

    expect(wrapper.get('[role="status"]').text()).toContain('Starting WatchParty')
    expect(wrapper.find('[data-testid="route"]').exists()).toBe(false)

    finishStartup({ require_login: false })
    await flushPromises()

    expect(wrapper.find('[role="status"]').exists()).toBe(false)
    expect(wrapper.get('[data-testid="route"]').text()).toBe('route')
  })

  it('shows startup failures and retries from the Vue UI', async () => {
    vi.mocked(api.authStatus)
      .mockRejectedValueOnce(new Error('Backend unavailable'))
      .mockResolvedValueOnce({ require_login: false })

    const wrapper = mount(App, {
      global: {
        plugins: [createPinia()],
        stubs: { RouterView: { template: '<div data-testid="route">route</div>' } },
      },
    })
    await flushPromises()

    expect(wrapper.get('[role="status"]').text()).toContain('Backend unavailable')
    await wrapper.get('button').trigger('click')
    await flushPromises()

    expect(api.authStatus).toHaveBeenCalledTimes(2)
    expect(wrapper.get('[data-testid="route"]').text()).toBe('route')
  })
})
