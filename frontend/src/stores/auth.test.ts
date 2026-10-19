import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api, type AuthResponse } from '@/api/client'
import { useAuthStore } from './auth'

const { listeners } = vi.hoisted(() => ({
  listeners: new Map<string, (payload: unknown) => void>(),
}))

vi.mock('./socket', () => ({
  useSocketStore: () => ({
    on: (event: string, listener: (payload: unknown) => void) => listeners.set(event, listener),
    off: (event: string) => listeners.delete(event),
  }),
}))

const HOST: AuthResponse = {
  is_host: true, is_admin: true, host_username: 'Alice', username: 'Alice',
  party_unlocked: true, party_id: 'ABCDE', media_server_type: 'emby',
}
const GUEST: AuthResponse = {
  is_host: false, is_admin: false, host_username: null, username: null,
  party_unlocked: false, party_id: 'ABCDE', media_server_type: 'emby',
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

describe('host authentication while binding and reconnecting', () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    listeners.clear()
    setActivePinia(createPinia())
  })

  it('ignores the pre-join response when the bound status finished first', async () => {
    const beforeJoin = deferred<AuthResponse>()
    const bound = deferred<AuthResponse>()
    vi.spyOn(api, 'authStatus').mockReturnValueOnce(beforeJoin.promise).mockReturnValueOnce(bound.promise)
    const auth = useAuthStore()
    const older = auth.refresh()
    const newer = auth.refresh()

    bound.resolve(HOST)
    await newer
    beforeJoin.resolve(GUEST)
    await older

    expect(auth.isHost).toBe(true)
    expect(auth.isAdmin).toBe(true)
    expect(auth.authenticated).toBe(true)
    expect(auth.partyUnlocked).toBe(true)
  })

  it('keeps reclaimed room presence while still accepting the bound host roles', async () => {
    const status = deferred<AuthResponse>()
    vi.spyOn(api, 'authStatus').mockReturnValue(status.promise)
    const auth = useAuthStore()
    auth.attachSocketListeners()
    const pending = auth.refresh()
    listeners.get('host_reclaimed')!({ host_username: 'Alice' })

    // The cookie proves the role before the socket has restored presence.
    status.resolve({ ...HOST, party_unlocked: false })
    await pending

    expect(auth.isHost).toBe(true)
    expect(auth.isAdmin).toBe(true)
    expect(auth.partyUnlocked).toBe(true)
    expect(auth.hostUsername).toBe('Alice')
  })

  it('does not restore host privileges from a response preceding a full host departure', async () => {
    const status = deferred<AuthResponse>()
    vi.spyOn(api, 'authStatus').mockReturnValue(status.promise)
    const auth = useAuthStore()
    auth.attachSocketListeners()
    const pending = auth.refresh()
    listeners.get('host_left')!({ playing_only: false })
    status.resolve(HOST)
    await pending

    expect(auth.isHost).toBe(false)
    expect(auth.isAdmin).toBe(false)
    expect(auth.authenticated).toBe(false)
    expect(auth.partyUnlocked).toBe(false)
    expect(auth.hostUsername).toBeNull()
  })

  it('keeps playing-only presence locked when an earlier status finishes', async () => {
    const status = deferred<AuthResponse>()
    vi.spyOn(api, 'authStatus').mockResolvedValueOnce(HOST).mockReturnValueOnce(status.promise)
    const auth = useAuthStore()
    auth.attachSocketListeners()
    await auth.refresh()
    const pending = auth.refresh()
    listeners.get('host_left')!({ playing_only: true })
    status.resolve(HOST)
    await pending

    expect(auth.isHost).toBe(true)
    expect(auth.isAdmin).toBe(true)
    expect(auth.partyUnlocked).toBe(false)
  })

  it('revalidates our roles when another member becomes host', async () => {
    const older = deferred<AuthResponse>()
    const takeover = deferred<AuthResponse>()
    const status = vi.spyOn(api, 'authStatus')
      .mockResolvedValueOnce(HOST).mockReturnValueOnce(older.promise).mockReturnValueOnce(takeover.promise)
    const auth = useAuthStore()
    auth.attachSocketListeners()
    await auth.refresh()
    const pending = auth.refresh()
    listeners.get('host_changed')!({ host_username: 'Bob', unlocked: true, is_admin: true })
    expect(status).toHaveBeenCalledTimes(3)
    takeover.resolve({ ...GUEST, host_username: 'Bob', party_unlocked: true })
    await flushPromises()
    older.resolve(HOST)
    await pending

    expect(auth.isHost).toBe(false)
    expect(auth.isAdmin).toBe(false)
    expect(auth.hostUsername).toBe('Bob')
    expect(auth.partyUnlocked).toBe(true)
  })

  it('never grants our host or admin role from a public host event', async () => {
    const status = deferred<AuthResponse>()
    vi.spyOn(api, 'authStatus').mockReturnValue(status.promise)
    const auth = useAuthStore()
    auth.attachSocketListeners()
    listeners.get('host_changed')!({ host_username: 'Alice', unlocked: true, is_admin: true })
    expect(auth.isHost).toBe(false)
    expect(auth.isAdmin).toBe(false)
    status.resolve({ ...GUEST, host_username: 'Alice', party_unlocked: true })
    await flushPromises()
    expect(auth.isHost).toBe(false)
    expect(auth.isAdmin).toBe(false)
  })

  it('does not let a delayed login response overwrite a verified host takeover', async () => {
    const login = deferred<AuthResponse>()
    vi.spyOn(api, 'login').mockReturnValue(login.promise)
    vi.spyOn(api, 'authStatus')
      .mockResolvedValueOnce({ ...GUEST, host_username: 'Alice', party_unlocked: true })
      .mockResolvedValue({ ...GUEST, host_username: 'Bob', party_unlocked: true })
    const auth = useAuthStore()
    auth.attachSocketListeners()
    const authenticating = auth.becomeHost('Alice', 'password')
    listeners.get('host_changed')!({ host_username: 'Alice', unlocked: true })
    await flushPromises()
    listeners.get('host_changed')!({ host_username: 'Bob', unlocked: true })
    await flushPromises()
    expect(auth.hostUsername).toBe('Bob')

    login.resolve({ ...HOST, success: true })
    await authenticating

    expect(auth.isHost).toBe(false)
    expect(auth.isAdmin).toBe(false)
    expect(auth.hostUsername).toBe('Bob')
  })

  it('does not let a status request started during login undo that login', async () => {
    const login = deferred<AuthResponse>()
    const status = deferred<AuthResponse>()
    vi.spyOn(api, 'login').mockReturnValue(login.promise)
    vi.spyOn(api, 'authStatus').mockReturnValueOnce(status.promise).mockResolvedValue(HOST)
    const auth = useAuthStore()
    const authenticating = auth.becomeHost('Alice', 'password')
    const pending = auth.refresh()
    login.resolve({ ...HOST, success: true })
    await authenticating
    status.resolve(GUEST)
    await pending

    expect(auth.isHost).toBe(true)
    expect(auth.isAdmin).toBe(true)
    expect(auth.partyUnlocked).toBe(true)
  })

  it('does not restore privileges from a response started during logout', async () => {
    const logout = deferred<{ success: boolean }>()
    const status = deferred<AuthResponse>()
    vi.spyOn(api, 'logout').mockReturnValue(logout.promise)
    vi.spyOn(api, 'authStatus').mockResolvedValueOnce(HOST).mockReturnValueOnce(status.promise)
    const auth = useAuthStore()
    await auth.refresh()
    const loggingOut = auth.dropHost()
    const pending = auth.refresh()
    logout.resolve({ success: true })
    await loggingOut
    status.resolve(HOST)
    await pending

    expect(auth.isHost).toBe(false)
    expect(auth.isAdmin).toBe(false)
    expect(auth.authenticated).toBe(false)
    expect(auth.partyUnlocked).toBe(false)
  })

  it('still accepts a current response that revokes our roles', async () => {
    vi.spyOn(api, 'authStatus').mockResolvedValueOnce(HOST).mockResolvedValueOnce(GUEST)
    const auth = useAuthStore()
    await auth.refresh()
    await auth.refresh()
    expect(auth.isHost).toBe(false)
    expect(auth.isAdmin).toBe(false)
    expect(auth.partyUnlocked).toBe(false)
  })
})
