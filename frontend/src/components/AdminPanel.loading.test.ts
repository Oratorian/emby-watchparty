import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, type AdminConfig, api } from '@/api/client'
import AdminPanel from './AdminPanel.vue'

const CONFIG: AdminConfig = {
  BINGE_WATCH_COUNTDOWN_SECONDS: 4,
  BINGE_WATCH_ENABLED: false,
  CONSOLE_LOG_LEVEL: 'WARNING',
  ENABLED_QUALITY_OPTIONS: { '1080p': [10000] },
  ENABLE_RATE_LIMITING: true,
  FORCE_TRANSCODE: true,
  HLS_TOKEN_EXPIRY: 86400,
  LATE_JOIN_VOTE_COOLDOWN_SECONDS: 30,
  LATE_JOIN_VOTE_ENABLED: true,
  LATE_JOIN_VOTE_TIMEOUT_SECONDS: 20,
  LOG_FILE: 'logs/party.log',
  LOG_FORMAT: 'rsyslog',
  LOG_LEVEL: 'INFO',
  LOG_MAX_SIZE: 10,
  LOG_TO_FILE: true,
  MAX_USERS_PER_PARTY: 7,
  RATE_LIMIT_API_CALLS: '1000 per minute',
  RATE_LIMIT_AVATAR_RECOVERY: '10 per hour',
  RATE_LIMIT_CHAT: '5 per 3 seconds',
  RATE_LIMIT_LOGIN: '10 per 15 minutes',
  RATE_LIMIT_PARTY_CREATION: '5 per hour',
  RATE_LIMIT_SOCKET_CONNECTIONS: '30 per minute',
  REQUIRE_LOGIN: false,
  STATIC_SESSION_ENABLED: false,
  STATIC_SESSION_ID: 'PARTY',
}

function mountPanel(onUnauthorized = vi.fn()) {
  return mount(AdminPanel, {
    props: { onUnauthorized },
    global: { plugins: [createPinia()] },
  })
}

function storedConfig() {
  return structuredClone(CONFIG)
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('loading administrator settings', () => {
  it('waits for a complete config before allowing editing or saving', async () => {
    let resolve!: (value: AdminConfig) => void
    vi.spyOn(api, 'adminGetConfig').mockReturnValue(new Promise((done) => { resolve = done }))
    const onUnauthorized = vi.fn()
    const wrapper = mountPanel(onUnauthorized)

    expect(wrapper.get('[role="status"]').text()).toBe('Loading settings...')
    expect(wrapper.get('.admin-panel-footer button').attributes('disabled')).toBeDefined()
    expect(wrapper.find('.admin-grid').exists()).toBe(false)

    resolve({ ...storedConfig(), error: null } as unknown as AdminConfig)
    await flushPromises()

    expect(wrapper.find('[role="status"]').exists()).toBe(false)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.get('.admin-panel-footer button').attributes('disabled')).toBeUndefined()
    expect((wrapper.get('input[aria-label="Force Transcode"]').element as HTMLInputElement).checked).toBe(true)
    expect(onUnauthorized).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it.each([
    ['network failure', () => Promise.reject(new TypeError('Failed to fetch'))],
    ['upstream failure', () => Promise.reject(new ApiError(503, 'Service unavailable', undefined))],
    ['rate limit', () => Promise.reject(new ApiError(429, 'Try again in 30 seconds.', undefined))],
    ['HTML with HTTP 200', () => Promise.resolve('<html>Proxy unavailable</html>')],
    ['empty JSON', () => Promise.resolve({})],
    ['empty body', () => Promise.resolve(undefined)],
    ['malformed setting', () => Promise.resolve({ ...storedConfig(), FORCE_TRANSCODE: 'true' })],
    ['ordinary error payload', () => Promise.resolve({ error: 'Settings unavailable' })],
  ])('keeps %s recoverable without declaring the session unauthorized', async (_name, failure) => {
    const getConfig = vi.spyOn(api, 'adminGetConfig')
      .mockImplementationOnce(() => failure() as Promise<AdminConfig>)
      .mockResolvedValue(storedConfig())
    const updateConfig = vi.spyOn(api, 'adminUpdateConfig')
    const onUnauthorized = vi.fn()
    const wrapper = mountPanel(onUnauthorized)
    await flushPromises()

    expect(wrapper.get('[role="alert"]').text()).toContain('Retry')
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
    expect(wrapper.find('.admin-grid').exists()).toBe(false)
    expect(wrapper.get('.admin-panel-footer button').attributes('disabled')).toBeDefined()
    expect(onUnauthorized).not.toHaveBeenCalled()
    await wrapper.get('.admin-panel-footer button').trigger('click')
    expect(updateConfig).not.toHaveBeenCalled()

    await wrapper.get('[role="alert"] button').trigger('click')
    await flushPromises()

    expect(getConfig).toHaveBeenCalledTimes(2)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    expect(wrapper.find('.admin-grid').exists()).toBe(true)
    expect(wrapper.get('.admin-panel-footer button').attributes('disabled')).toBeUndefined()
    expect(onUnauthorized).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it.each([
    ['401', () => Promise.reject(new ApiError(401, 'Not authenticated', undefined))],
    ['403', () => Promise.reject(new ApiError(403, 'Forbidden', undefined))],
    ['current backend refusal', () => Promise.resolve({ error: 'Not authenticated' })],
    ['explicit unauthorized refusal', () => Promise.resolve({ error: 'Unauthorized' })],
  ])('still gates settings after a confirmed %s', async (_name, failure) => {
    vi.spyOn(api, 'adminGetConfig').mockImplementation(() => failure() as Promise<AdminConfig>)
    const onUnauthorized = vi.fn()
    const wrapper = mountPanel(onUnauthorized)
    await flushPromises()

    expect(onUnauthorized).toHaveBeenCalledTimes(1)
    expect(wrapper.find('.admin-grid').exists()).toBe(false)
    expect(wrapper.get('.admin-panel-footer button').attributes('disabled')).toBeDefined()
    wrapper.unmount()
  })

  it('aborts on close and ignores an authentication error that arrives afterwards', async () => {
    let reject!: (reason: unknown) => void
    const getConfig = vi.spyOn(api, 'adminGetConfig').mockReturnValue(
      new Promise((_resolve, fail) => { reject = fail }),
    )
    const onUnauthorized = vi.fn()
    const wrapper = mountPanel(onUnauthorized)

    wrapper.unmount()
    expect(getConfig.mock.calls[0]![0]?.aborted).toBe(true)
    reject(new ApiError(401, 'Not authenticated', undefined))
    await flushPromises()

    expect(onUnauthorized).not.toHaveBeenCalled()
  })
})

describe('saving administrator settings', () => {
  it('keeps an edited draft after a temporary save failure and retries that draft', async () => {
    vi.spyOn(api, 'adminGetConfig').mockResolvedValue(storedConfig())
    const updateConfig = vi.spyOn(api, 'adminUpdateConfig')
      .mockRejectedValueOnce(new ApiError(503, 'Service unavailable', undefined))
      .mockResolvedValue({ success: true } as never)
    const onUnauthorized = vi.fn()
    const wrapper = mountPanel(onUnauthorized)
    await flushPromises()

    await wrapper.get('input[aria-label="Chat Limit"]').setValue(9)
    await wrapper.get('.admin-panel-footer button').trigger('click')
    await flushPromises()

    expect(wrapper.get('.save-status.error').text()).toBe('Service unavailable')
    expect((wrapper.get('input[aria-label="Chat Limit"]').element as HTMLInputElement).value).toBe('9')
    expect(wrapper.get('.admin-panel-footer button').attributes('disabled')).toBeUndefined()
    expect(onUnauthorized).not.toHaveBeenCalled()

    await wrapper.get('.admin-panel-footer button').trigger('click')
    await flushPromises()

    expect(updateConfig).toHaveBeenCalledTimes(2)
    expect(updateConfig.mock.calls[1]![0]).toMatchObject({
      RATE_LIMIT_CHAT: '9 per 3 seconds',
      FORCE_TRANSCODE: true,
      MAX_USERS_PER_PARTY: 7,
    })
    expect(wrapper.get('.save-status.success').text()).toBe('No changes')
    wrapper.unmount()
  })
})
