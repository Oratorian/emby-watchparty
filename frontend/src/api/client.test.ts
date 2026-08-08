import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError, api, apiFetch, type AdminConfig } from './client'

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

  it('preserves structured rate-limit details and Retry-After', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({
        detail: 'Too many party join attempts. Try again in 42 seconds.',
        code: 'rate_limited',
        retry_after: 42,
      }),
      {
        status: 429,
        headers: { 'Content-Type': 'application/json', 'Retry-After': '42' },
      },
    )))

    await expect(api.joinParty('ABC123', 'client-1', 'Alice')).rejects.toMatchObject({
      status: 429,
      message: 'Too many party join attempts. Try again in 42 seconds.',
      code: 'rate_limited',
      retryAfter: 42,
    })
  })

  it('preserves readable multipart upload errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      'Upload too large',
      { status: 413, statusText: 'Content Too Large' },
    )))

    await expect(api.avatarUpload(new File(['x'], 'avatar.png'))).rejects.toEqual(
      new ApiError(413, 'Upload too large', 'Upload too large'),
    )
  })

  it('keeps HLS validation out of runtime admin updates', async () => {
    const config: AdminConfig = {
      BINGE_WATCH_COUNTDOWN_SECONDS: 10,
      BINGE_WATCH_ENABLED: true,
      CONSOLE_LOG_LEVEL: 'INFO',
      ENABLED_QUALITY_OPTIONS: { auto: [] },
      ENABLE_RATE_LIMITING: true,
      FORCE_TRANSCODE: false,
      HLS_TOKEN_EXPIRY: 300,
      LATE_JOIN_VOTE_COOLDOWN_SECONDS: 30,
      LATE_JOIN_VOTE_ENABLED: true,
      LATE_JOIN_VOTE_TIMEOUT_SECONDS: 30,
      LOG_FILE: 'watchparty.log',
      LOG_FORMAT: 'text',
      LOG_LEVEL: 'INFO',
      LOG_MAX_SIZE: 10,
      LOG_TO_FILE: false,
      MAX_USERS_PER_PARTY: 20,
      RATE_LIMIT_API_CALLS: '100/minute',
      RATE_LIMIT_AVATAR_RECOVERY: '5/minute',
      RATE_LIMIT_CHAT: '30/minute',
      RATE_LIMIT_LOGIN: '5/minute',
      RATE_LIMIT_PARTY_CREATION: '5/minute',
      RATE_LIMIT_SOCKET_CONNECTIONS: '20/minute',
      REQUIRE_LOGIN: false,
      STATIC_SESSION_ENABLED: false,
      STATIC_SESSION_ID: '',
    }
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ success: true, changed: [], rejected: [], restart_required: [] }),
      { status: 200 },
    ))
    vi.stubGlobal('fetch', fetchMock)

    await api.adminUpdateConfig(config)

    const request = fetchMock.mock.calls[0]![1] as RequestInit
    const payload = JSON.parse(request.body as string) as Record<string, unknown>
    expect(payload).toEqual(config)
    expect(payload).not.toHaveProperty('ENABLE_HLS_TOKEN_VALIDATION')
  })
})
