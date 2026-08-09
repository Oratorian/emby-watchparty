import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, api } from '@/api/client'
import IndexView from './IndexView.vue'

const push = vi.fn()

vi.mock('vue-router', () => ({
  useRouter: () => ({ push, replace: vi.fn() }),
}))

describe('party creation failures', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    push.mockReset()
    vi.spyOn(api, 'listParties').mockResolvedValue({ require_login: false, parties: [] })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', { status: 200 })))
  })

  it('shows the backend rate-limit detail instead of leaving an unhandled request', async () => {
    vi.spyOn(api, 'createParty').mockRejectedValue(new ApiError(
      429,
      'Too many party creation attempts. Try again in 60 seconds.',
      { code: 'rate_limited', retry_after: 60 },
      'rate_limited',
      60,
    ))
    const wrapper = mount(IndexView, {
      global: {
        plugins: [createPinia()],
        stubs: { EmbyLoginModal: true, RouterLink: true },
      },
    })

    await wrapper.get('.action-card button').trigger('click')
    await flushPromises()

    expect(wrapper.get('.status-msg').text()).toBe(
      'Too many party creation attempts. Try again in 60 seconds.',
    )
    expect(push).not.toHaveBeenCalled()
  })

  it('shows one contextual status when party-list polling is limited', async () => {
    vi.mocked(api.listParties).mockRejectedValue(new ApiError(
      429,
      'Too many requests. Try again in 15 seconds.',
      { code: 'rate_limited', retry_after: 15 },
      'rate_limited',
      15,
    ))

    const wrapper = mount(IndexView, {
      global: {
        plugins: [createPinia()],
        stubs: { EmbyLoginModal: true, RouterLink: true },
      },
    })
    await flushPromises()

    expect(wrapper.get('[data-testid="party-list-status"]').text()).toBe(
      'Too many requests. Try again in 15 seconds.',
    )
  })
})
