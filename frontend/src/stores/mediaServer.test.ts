import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { api } from '@/api/client'
import { useMediaServerStore } from './mediaServer'

describe('media server capabilities', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.restoreAllMocks()
  })

  it('caches a valid boot-stable capability response', async () => {
    const request = vi.spyOn(api, 'mediaServerInfo').mockResolvedValue({
      media_server_type: 'jellyfin',
      display_name: 'Jellyfin',
      capabilities: { filter_controls: false },
    })
    const store = useMediaServerStore()

    await store.load()
    await store.load()

    expect(request).toHaveBeenCalledTimes(1)
    expect(store.filterControlsSupported).toBe(false)
  })

  it('defaults to supported and retries failed or incomplete responses', async () => {
    const request = vi.spyOn(api, 'mediaServerInfo')
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce({
        media_server_type: 'jellyfin',
        display_name: 'Jellyfin',
      } as never)
      .mockResolvedValueOnce({
        media_server_type: 'jellyfin',
        display_name: 'Jellyfin',
        capabilities: { filter_controls: false },
      })
    const store = useMediaServerStore()

    await expect(store.load()).resolves.toBe(true)
    await expect(store.load()).resolves.toBe(true)
    await expect(store.load()).resolves.toBe(false)

    expect(request).toHaveBeenCalledTimes(3)
    expect(store.filterControlsSupported).toBe(false)
  })
})
