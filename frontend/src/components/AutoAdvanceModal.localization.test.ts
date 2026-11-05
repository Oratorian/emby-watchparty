import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { nextTick } from 'vue'
import { afterEach, expect, it, vi } from 'vitest'
import { setLanguagePreference } from '@/i18n'
import { usePartyStore } from '@/stores/party'
import AutoAdvanceModal from './AutoAdvanceModal.vue'

afterEach(() => {
  setLanguagePreference('en')
  vi.useRealTimers()
})

it('translates a live countdown while preserving its emphasized value and timer', async () => {
  vi.useFakeTimers()
  const pinia = createPinia()
  setActivePinia(pinia)
  const party = usePartyStore()
  party.pendingAutoAdvance = {
    nextItemId: 'episode-2', nextTitle: 'Next episode', nextIndexNumber: 2,
    totalEpisodes: 6, timeoutAt: Date.now() + 4000, countdownSeconds: 4,
  }
  setLanguagePreference('en')
  const wrapper = mount(AutoAdvanceModal, { global: { plugins: [pinia] } })
  expect(wrapper.get('.countdown').text()).toBe('Playing in 4s')
  expect(wrapper.get('.countdown strong').text()).toBe('4s')
  setLanguagePreference('de')
  await nextTick()
  expect(wrapper.get('.countdown').text()).toBe('Wiedergabe in 4s')
  expect(wrapper.get('.countdown strong').text()).toBe('4s')
  await vi.advanceTimersByTimeAsync(1000)
  expect(wrapper.get('.countdown strong').text()).toBe('3s')
  expect(party.pendingAutoAdvance.nextItemId).toBe('episode-2')
  wrapper.unmount()
})
