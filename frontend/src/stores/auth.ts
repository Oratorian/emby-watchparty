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

  async function refresh() {
    const data = await api.authStatus()
    requireLogin.value = !!data.require_login
    isHost.value = !!data.is_host
    isAdmin.value = !!data.is_admin
    hostUsername.value = data.host_username || null
    partyUnlocked.value = !!data.party_unlocked
    partyId.value = data.party_id || null
    username.value = data.username || null
    authenticated.value = isHost.value
    mediaServerType.value = data.media_server_type || 'emby'
  }

  /** Promote this party-bound caller to host of their current party. */
  async function becomeHost(emby_username: string, password: string) {
    const data = await api.login(emby_username, password)
    if (data.success) {
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
    await api.logout()
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
      hostUsername.value = data.host_username || null
      partyUnlocked.value = !!data.unlocked
      // is_host stays whatever it was -- the caller knows from /auth/status
      // whether they themselves were the one becoming host.
    })

    socket.on('host_left', (data: ServerToClientPayloads['host_left']) => {
      const wasPlayingOnly = !!data.playing_only
      partyUnlocked.value = false
      if (!wasPlayingOnly) {
        // Full lock; clear all host context for everyone.
        hostUsername.value = null
        isHost.value = false
        isAdmin.value = false
        authenticated.value = false
      }
    })

    socket.on('host_reclaimed', (data: ServerToClientPayloads['host_reclaimed']) => {
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
