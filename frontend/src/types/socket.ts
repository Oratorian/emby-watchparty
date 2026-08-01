export type SocketPayload = Record<string, unknown>

export interface ServerToClientEvents {
  connect: () => void
  disconnect: (reason: string) => void
  connect_error: (error: Error) => void
  connected: (data: { sid: string }) => void
  user_joined: (data: SocketPayload) => void
  user_left: (data: SocketPayload) => void
  members_update: (data: SocketPayload) => void
  sync_state: (data: SocketPayload) => void
  video_selected: (data: SocketPayload) => void
  video_stopped: (data?: SocketPayload) => void
  video_ended: (data?: SocketPayload) => void
  play: (data: SocketPayload) => void
  pause: (data: SocketPayload) => void
  seek: (data: SocketPayload) => void
  streams_changed: (data: SocketPayload) => void
  ready_check_update: (data: SocketPayload) => void
  all_ready: (data: SocketPayload) => void
  force_pause_before_seek: (data?: SocketPayload) => void
  drift_correction: (data: SocketPayload) => void
  chat_message: (data: SocketPayload) => void
  toggle_library: (data: SocketPayload) => void
  host_changed: (data: SocketPayload) => void
  host_left: (data: SocketPayload) => void
  host_reclaimed: (data: SocketPayload) => void
  join_vote_started: (data: SocketPayload) => void
  join_vote_pending: (data: SocketPayload) => void
  join_vote_update: (data: SocketPayload) => void
  join_vote_resolved: (data: SocketPayload) => void
  join_rejected: (data: SocketPayload) => void
  binge_watch_state_changed: (data: SocketPayload) => void
  auto_advance_pending: (data: SocketPayload) => void
  auto_advance_cancelled: (data?: SocketPayload) => void
  auto_advance_fired: (data?: SocketPayload) => void
  binge_finished: (data?: SocketPayload) => void
  party_dissolved: (data?: SocketPayload) => void
  error: (data: SocketPayload) => void
}

export type ClientToServerEvents = {
  [Event in keyof ClientToServerPayloads]: (data: ClientToServerPayloads[Event]) => void
}
import type { ClientToServerPayloads } from './socket.generated'
