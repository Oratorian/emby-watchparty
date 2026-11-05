import { flushPromises, mount, type VueWrapper } from '@vue/test-utils'
import { createPinia } from 'pinia'
import { nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { api, type AdminConfig } from '@/api/client'
import { i18n } from '@/i18n'
import AdminPanel from './AdminPanel.vue'

const config: AdminConfig = {
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
  LOG_FILE: 'logs/test.log',
  LOG_FORMAT: 'standard',
  LOG_LEVEL: 'INFO',
  LOG_MAX_SIZE: 10,
  LOG_TO_FILE: true,
  MAX_USERS_PER_PARTY: 10,
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

let wrapper: VueWrapper | undefined

afterEach(() => {
  wrapper?.unmount()
  wrapper = undefined
  i18n.global.locale.value = 'en'
  vi.restoreAllMocks()
})

describe('localized admin configuration', () => {
  it('switches rate labels in place and saves the original protocol values', async () => {
    i18n.global.locale.value = 'en'
    vi.spyOn(api, 'adminGetConfig').mockResolvedValue(structuredClone(config))
    const update = vi.spyOn(api, 'adminUpdateConfig').mockResolvedValue({
      success: true, changed: [], rejected: [], restart_required: [],
    })
    wrapper = mount(AdminPanel, { global: { plugins: [createPinia()] } })
    await flushPromises()

    const loginWindow = wrapper.get('select[aria-label="Admin Login Limit window"]')
    expect((loginWindow.element as HTMLSelectElement).selectedOptions[0]?.textContent)
      .toBe('per 15 minutes')

    i18n.global.locale.value = 'de'
    await nextTick()

    // The same control updates its accessible label and option text without
    // remounting or rewriting the English value understood by the backend.
    expect(loginWindow.attributes('aria-label')).toBe('Zeitraum für Limit Admin-Anmeldungen')
    expect((loginWindow.element as HTMLSelectElement).selectedOptions[0]?.textContent)
      .toBe('pro 15 Minuten')
    expect((loginWindow.element as HTMLSelectElement).value).toBe('per 15 minutes')

    const chatWindow = wrapper.get('select[aria-label="Zeitraum für Chat-Limit"]')
    expect((chatWindow.element as HTMLSelectElement).selectedOptions[0]?.textContent)
      .toBe('pro 3 Sekunden')
    await wrapper.get('input[aria-label="Chat-Limit"]').setValue(9)
    await chatWindow.setValue('per 10 seconds')
    expect((chatWindow.element as HTMLSelectElement).selectedOptions[0]?.textContent)
      .toBe('pro 10 Sekunden')

    expect(wrapper.get('.admin-panel-footer .btn-primary').text()).toBe('Einstellungen speichern')
    await wrapper.get('.admin-panel-footer .btn-primary').trigger('click')
    await flushPromises()

    expect(update).toHaveBeenCalledTimes(1)
    expect(update.mock.calls[0]?.[0]).toMatchObject({
      RATE_LIMIT_LOGIN: '10 per 15 minutes',
      RATE_LIMIT_CHAT: '9 per 10 seconds',
      RATE_LIMIT_AVATAR_RECOVERY: '10 per hour',
      RATE_LIMIT_SOCKET_CONNECTIONS: '30 per minute',
      RATE_LIMIT_API_CALLS: '1000 per minute',
      RATE_LIMIT_PARTY_CREATION: '5 per hour',
    })
  })

  it('retranslates an existing local validation error without changing the invalid value', async () => {
    i18n.global.locale.value = 'en'
    vi.spyOn(api, 'adminGetConfig').mockResolvedValue({
      ...structuredClone(config), RATE_LIMIT_CHAT: '5/minute',
    })
    const update = vi.spyOn(api, 'adminUpdateConfig')
    wrapper = mount(AdminPanel, { global: { plugins: [createPinia()] } })
    await flushPromises()
    await wrapper.get('.admin-panel-footer .btn-primary').trigger('click')
    expect(wrapper.get('.save-status').text()).toBe('Chat Limit must be at least 1')

    i18n.global.locale.value = 'de'
    await nextTick()

    expect(wrapper.get('.save-status').text()).toBe('Chat-Limit muss mindestens 1 sein')
    expect((wrapper.get('input[aria-label="Chat-Limit"]').element as HTMLInputElement).value)
      .toBe('0')
    expect(update).not.toHaveBeenCalled()
  })
})
