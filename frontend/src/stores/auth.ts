import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { api } from '@/api/client'
import { useSocketStore } from './socket'
import type { ServerToClientPayloads } from '@/types/socket.generated'

/**
 * Per-party auth state.
 *
 * The 2.0 model has no global "logged-in user." Authentication is the
 * act of any party member promoting themselves to that party's host,
 * which unlocks the library for everyone in the room.
 *
 * - `requireLogin` is the runtime admin toggle (REQUIRE_LOGIN). When
 *   true, even creating a party requires Emby credentials.
 * - `isHost` is true when the caller IS the host of their current party.
 * - `hostUsername` / `hostIsAdmin` describe the current host (anyone).
 * - `partyUnlocked` is true when a host is present and the library is
 *   browsable. When it flips false, the UI shows "Login to Become Host".
 */
export const useAuthStore = defineStore('auth', () => {
  // Runtime config from backend
  const requireLogin = ref(false)

  // Identity / role within the current party
  const isHost = ref(false)
  const isAdmin = ref(false)
  const hostUsername = ref<string | null>(null)
  const partyUnlocked = ref(false)
  const partyId = ref<string | null>(null)
  const mediaServerType = ref<'emby' | 'jellyfin'>('emby')
  const mediaServerName = computed(() => mediaServerType.value === 'jellyfin' ? 'Jellyfin' : 'Emby')

  // Display username (the host's Emby account name when we're host;
  // otherwise the spectator's display name from the join modal).
  const username = ref<string | null>(null)

  // Backwards-compat alias for templates still checking `authenticated`.
  // True only when this caller is the current host.
  const authenticated = ref(false)

  // HTTP status requests can finish out of order during session binding.
  // Socket presence events are newer than the room snapshot of an in-flight
  // request, but that request may still carry the first valid host/admin roles.
  let statusRequest = 0
  let roomRevision = 0
  let authAction = 0

  async function refresh() {
    const request = ++statusRequest
    const roomAtRequest = roomRevision
    const data = await api.authStatus()
    if (request !== statusRequest) return
    requireLogin.value = !!data.require_login
    isHost.value = !!data.is_host
    isAdmin.value = !!data.is_admin
    if (roomAtRequest === roomRevision) {
      hostUsername.value = data.host_username || null
      partyUnlocked.value = !!data.party_unlocked
    }
    partyId.value = data.party_id || null
    username.value = data.username || null
    authenticated.value = isHost.value
    mediaServerType.value = data.media_server_type || 'emby'
  }

  /** Promote this party-bound caller to host of their current party. */
  async function becomeHost(emby_username: string, password: string) {
    const action = ++authAction
    ++statusRequest
    const data = await api.login(emby_username, password)
    if (action !== authAction) return data
    if (data.success) {
      ++statusRequest
      ++roomRevision
      mediaServerType.value = data.media_server_type || mediaServerType.value
      isHost.value = true
      isAdmin.value = !!data.is_admin
      hostUsername.value = data.host_username ?? null
      partyUnlocked.value = true
      username.value = data.host_username ?? null
      authenticated.value = true
    }
    return data
  }

  /** Step down as host (party stays joined). */
  async function dropHost() {
    const action = ++authAction
    ++statusRequest
    await api.logout()
    if (action !== authAction) return
    ++statusRequest
    ++roomRevision
    isHost.value = false
    isAdmin.value = false
    hostUsername.value = null
    partyUnlocked.value = false
    authenticated.value = false
  }

  /** Wire socket events that drive partyUnlocked / hostUsername. */
  function attachSocketListeners() {
    const socket = useSocketStore()
    socket.off('host_changed')
    socket.off('host_left')
    socket.off('host_reclaimed')

    socket.on('host_changed', (data: ServerToClientPayloads['host_changed']) => {
      ++roomRevision
      hostUsername.value = data.host_username || null
      partyUnlocked.value = !!data.unlocked
      // A public room event cannot prove our own host/admin role. Recheck the
      // cookie and supersede any status request made before the host changed.
      void refresh().catch(() => { /* keep the last verified roles on an outage */ })
    })

    socket.on('host_left', (data: ServerToClientPayloads['host_left']) => {
      ++roomRevision
      const wasPlayingOnly = !!data.playing_only
      partyUnlocked.value = false
      if (!wasPlayingOnly) {
        ++statusRequest
        // Full lock; clear all host context for everyone.
        hostUsername.value = null
        isHost.value = false
        isAdmin.value = false
        authenticated.value = false
      }
    })

    socket.on('host_reclaimed', (data: ServerToClientPayloads['host_reclaimed']) => {
      ++roomRevision
      hostUsername.value = data.host_username || hostUsername.value
      partyUnlocked.value = true
    })
  }

  return {
    requireLogin,
    isHost,
    isAdmin,
    hostUsername,
    partyUnlocked,
    partyId,
    username,
    authenticated,
    mediaServerType,
    mediaServerName,
    refresh,
    becomeHost,
    dropHost,
    attachSocketListeners,
  }
})
