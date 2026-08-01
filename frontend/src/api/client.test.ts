import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, api, apiFetch } from './client'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('apiFetch', () => {
  it('passes an AbortSignal through typed search requests', async () => {
    const controller = new AbortController()
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ Items: [], TotalRecordCount: 0 }),
      { status: 200 },
    ))
    vi.stubGlobal('fetch', fetchMock)

    await api.search('matrix', controller.signal)

    expect(fetchMock).toHaveBeenCalledWith(
      '/api/search?q=matrix',
      expect.objectContaining({ signal: controller.signal }),
    )
  })

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
