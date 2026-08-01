import { ref } from 'vue'
import { defineStore } from 'pinia'
import { useAuthStore } from './auth'

export type StartupState = 'idle' | 'starting' | 'ready' | 'failed'

/** Owns browser-app bootstrap. Kept in this scaffold file to preserve upgrades/history. */
export const useStartupStore = defineStore('startup', () => {
  const state = ref<StartupState>('idle')
  const error = ref<string | null>(null)

  async function start() {
    if (state.value === 'starting') return
    state.value = 'starting'
    error.value = null
    try {
      await useAuthStore().refresh()
      state.value = 'ready'
    } catch (cause) {
      error.value = cause instanceof Error ? cause.message : 'Backend unavailable'
      state.value = 'failed'
    }
  }

  return { state, error, start }
})
