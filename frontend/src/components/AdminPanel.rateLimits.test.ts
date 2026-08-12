import { flushPromises, mount } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { type AdminConfig, api } from '@/api/client'
import AdminPanel from './AdminPanel.vue'

/**
 * The rate-limit controls, which had no coverage of any kind.
 *
 * AdminView.test.ts mocks adminGetConfig to reject, so AdminPanel never
 * mounts there, and the admin e2e only exercises focus trapping. That left
 * every part of this uncovered: the parser, the writeback into the PUT
 * payload, the validation guard and the unknown-window fallback.
 *
 * All four fail silently and destructively. These fields are free text in the
 * environment, and the panel PUTs the whole config back, so a parse the panel
 * gets wrong is not displayed wrong -- it is written back wrong, replacing an
 * operator's working limit with whatever the panel managed to read.
 */

const BASE: AdminConfig = {
  BINGE_WATCH_COUNTDOWN_SECONDS: 10,
  BINGE_WATCH_ENABLED: false,
  CONSOLE_LOG_LEVEL: 'INFO',
  ENABLED_QUALITY_OPTIONS: { '1080p': [10000] },
  ENABLE_RATE_LIMITING: true,
  FORCE_TRANSCODE: false,
  HLS_TOKEN_EXPIRY: 3600,
  LATE_JOIN_VOTE_COOLDOWN_SECONDS: 30,
  LATE_JOIN_VOTE_ENABLED: true,
  LATE_JOIN_VOTE_TIMEOUT_SECONDS: 30,
  LOG_FILE: 'logs/app.log',
  LOG_FORMAT: 'plain',
  LOG_LEVEL: 'INFO',
  LOG_MAX_SIZE: 10,
  LOG_TO_FILE: true,
  MAX_USERS_PER_PARTY: 10,
  // The real backend defaults, both of which carry a multiplied window.
  RATE_LIMIT_API_CALLS: '1000 per minute',
  RATE_LIMIT_AVATAR_RECOVERY: '10 per hour',
  RATE_LIMIT_CHAT: '5 per 3 seconds',
  RATE_LIMIT_LOGIN: '10 per 15 minutes',
  RATE_LIMIT_PARTY_CREATION: '5 per hour',
  RATE_LIMIT_SOCKET_CONNECTIONS: '30 per minute',
  REQUIRE_LOGIN: false,
  STATIC_SESSION_ENABLED: false,
  STATIC_SESSION_ID: '',
}

async function mountPanel(overrides: Partial<AdminConfig> = {}) {
  vi.spyOn(api, 'adminGetConfig').mockResolvedValue({ ...BASE, ...overrides })
  const wrapper = mount(AdminPanel, { global: { plugins: [createPinia()] } })
  await flushPromises()
  return wrapper
}

function value(wrapper: ReturnType<typeof mount>, label: string): string {
  return (wrapper.get(`input[aria-label="${label}"]`).element as HTMLInputElement).value
}

function unit(wrapper: ReturnType<typeof mount>, label: string): string {
  return (wrapper.get(`select[aria-label="${label} window"]`).element as HTMLSelectElement).value
}

async function save(wrapper: ReturnType<typeof mount>) {
  await wrapper.get('.admin-panel-footer .btn-primary').trigger('click')
  await flushPromises()
}

describe('reading a stored rate limit into the controls', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('keeps the multiplier in a window like "per 15 minutes"', async () => {
    const wrapper = await mountPanel()

    // The previous regex captured the window as a single \w+, which swallowed
    // the number: '10 per 15 minutes' read back as '10 per minute', a
    // fifteen-fold tightening of the login limit written back on the next
    // save. Both shipped defaults have a multiplied window, so this was not
    // an edge case.
    expect(value(wrapper, 'Admin Login Limit')).toBe('10')
    expect(unit(wrapper, 'Admin Login Limit')).toBe('per 15 minutes')
    expect(value(wrapper, 'Chat Limit')).toBe('5')
    expect(unit(wrapper, 'Chat Limit')).toBe('per 3 seconds')
  })

  it('offers a window the environment set even when it is not one of ours', async () => {
    const wrapper = await mountPanel({ RATE_LIMIT_CHAT: '5 per 45 seconds' })

    // Dropping an unrecognised window would silently rewrite the operator's
    // configuration the first time anyone pressed Save.
    expect(unit(wrapper, 'Chat Limit')).toBe('per 45 seconds')
    const options = wrapper
      .get('select[aria-label="Chat Limit window"]')
      .findAll('option')
      .map((option) => (option.element as HTMLOptionElement).value)
    expect(options[0]).toBe('per 45 seconds')
    expect(options).toContain('per minute')

    // And a recognised one is not duplicated into the list.
    const known = await mountPanel({ RATE_LIMIT_CHAT: '5 per minute' })
    const knownOptions = known
      .get('select[aria-label="Chat Limit window"]')
      .findAll('option')
      .map((option) => (option.element as HTMLOptionElement).value)
    expect(knownOptions.filter((option) => option === 'per minute')).toHaveLength(1)
  })
})

describe('writing the controls back', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('sends what the operator selected, not what was loaded', async () => {
    const update = vi.spyOn(api, 'adminUpdateConfig').mockResolvedValue({ success: true } as never)
    const wrapper = await mountPanel()

    await wrapper.get('input[aria-label="Chat Limit"]').setValue(9)
    await wrapper.get('select[aria-label="Chat Limit window"]').setValue('per 10 seconds')
    await save(wrapper)

    // Without the writeback loop these four controls are decorative: every
    // edit is discarded and the old value is PUT straight back.
    expect(update).toHaveBeenCalledTimes(1)
    expect(update.mock.calls[0]![0]).toMatchObject({
      RATE_LIMIT_CHAT: '9 per 10 seconds',
      RATE_LIMIT_LOGIN: '10 per 15 minutes',
    })
  })

  it('round-trips an untouched config unchanged', async () => {
    const update = vi.spyOn(api, 'adminUpdateConfig').mockResolvedValue({ success: true } as never)
    const wrapper = await mountPanel()

    await save(wrapper)

    // Opening the panel and pressing Save must not edit anything. Parse and
    // serialise are separate functions, and only a round trip pins them to
    // each other.
    expect(update.mock.calls[0]![0]).toMatchObject({
      RATE_LIMIT_LOGIN: '10 per 15 minutes',
      RATE_LIMIT_CHAT: '5 per 3 seconds',
      RATE_LIMIT_AVATAR_RECOVERY: '10 per hour',
      RATE_LIMIT_SOCKET_CONNECTIONS: '30 per minute',
      RATE_LIMIT_API_CALLS: '1000 per minute',
      RATE_LIMIT_PARTY_CREATION: '5 per hour',
    })
  })
})

describe('refusing to save a limit the panel could not read', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
  })

  it('blocks the save rather than writing a zero back', async () => {
    const update = vi.spyOn(api, 'adminUpdateConfig').mockResolvedValue({ success: true } as never)
    // A legacy shorthand the current parser does not accept. It parses to
    // {value: 0}, and 0 serialises to '0 per minute' -- a working limit
    // replaced with one nobody can satisfy.
    const wrapper = await mountPanel({ RATE_LIMIT_CHAT: '5/minute' })

    expect(value(wrapper, 'Chat Limit')).toBe('0')

    await save(wrapper)

    expect(update).not.toHaveBeenCalled()
    expect(wrapper.get('.save-status').text()).toBe('Chat Limit must be at least 1')

    // And it is recoverable in place: fixing the field lets the save through.
    await wrapper.get('input[aria-label="Chat Limit"]').setValue(5)
    await save(wrapper)
    expect(update).toHaveBeenCalledTimes(1)
    expect(update.mock.calls[0]![0]).toMatchObject({ RATE_LIMIT_CHAT: '5 per minute' })
  })
})
