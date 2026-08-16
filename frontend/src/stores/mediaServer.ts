import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

import { api } from '@/api/client'
import type { MediaServerInfoV2 } from '@/types/api.generated'

export const useMediaServerStore = defineStore('media-server', () => {
  const info = ref<MediaServerInfoV2 | null>(null)
  const filterControlsSupported = computed(
    () => info.value?.capabilities?.filter_controls ?? true,
  )
  let inFlight: Promise<boolean> | null = null

  function load(): Promise<boolean> {
    if (info.value) return Promise.resolve(filterControlsSupported.value)
    if (inFlight) return inFlight

    inFlight = (async () => {
      try {
        const response = await api.mediaServerInfo()
        if (typeof response?.capabilities?.filter_controls === 'boolean') {
          info.value = response
        }
        return info.value?.capabilities.filter_controls ?? true
      } catch {
        return true
      } finally {
        inFlight = null
      }
    })()
    return inFlight
  }

  return { info, filterControlsSupported, load }
})
