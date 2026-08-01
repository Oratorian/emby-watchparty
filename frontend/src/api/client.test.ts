import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, apiFetch } from './client'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('apiFetch', () => {
  it('rejects non-success JSON responses with a typed error', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ detail: 'Party has no host' }),
      {
        status: 423,
        headers: { 'Content-Type': 'application/json' },
      },
    )))

    await expect(apiFetch('/api/libraries')).rejects.toEqual(
      new ApiError(423, 'Party has no host', { detail: 'Party has no host' }),
    )
  })
})
