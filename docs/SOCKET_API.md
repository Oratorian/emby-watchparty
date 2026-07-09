# Socket.IO API (2.0)

Real-time event surface for Emby Watch Party 2.0. The frontend's
`stores/socket.ts` wraps `socket.io-client` and the backend mounts a
`python-socketio.AsyncServer` under `${APP_PREFIX}/socket.io`. This
document covers every inbound event the server handles, every
outbound event clients can receive, and the multi-step flows that
weave them together.

For the REST surface (party create / join, library browsing, HLS
proxy, admin config) see the auto-generated OpenAPI docs at
`/docs` and `/redoc`.

---

## Conventions

- **`sid`** = transient Socket.IO session id. Issued per WebSocket
  connection, lost on disconnect.
- **`client_id`** = stable per-browser identifier from
  `localStorage`. Survives page refreshes, brief disconnects, and
  browser-tab transitions. Used for selector identity, vote
  attribution, host-reclaim grace, and rejoin detection.
- **`party_id`** = uppercase 6-character code, e.g. `K7N2QF`.
  Always normalised to upper-case on inbound.
- **Room** = Socket.IO room with the same name as the `party_id`.
  Every member of a party is in their party room; emits with
  `room=party_id` reach all members. `skip_sid=sid` excludes the
  originator (the sender's local UI already reflects the action).
- **`to=sid`** = emit to a single connection (private message to
  one client), e.g. errors, drift correction, the initial connect
  acknowledgement.

## Authentication

There is no global "logged in user." The auth surface is per-party:

- **Party-bound session cookie** (`ewp_session`, renamed from
  `session` in beta18) -- issued by `POST /api/party/<id>/join`.
  Carries `party_id`, `client_id`, `display_name`, and optionally
  `avatar_uuid`. Signed with `SESSION_SECRET` from `.env`. The
  Socket.IO `connect` handler decodes it for logging only and to
  gate host-reclaim proof; the actual party binding happens when
  the client emits `join_party`.
- **Host status** -- a member becomes host of their party by
  posting Emby credentials to `POST /api/auth/login`. The host's
  Emby `access_token` signs every backend->Emby call for the
  party until they log out, disconnect (and the grace window
  expires), or the party is stopped.
- **Three-state lock**:
  - `UNLOCKED` -- host present, library browseable, all events work.
  - `PLAYING-ONLY` -- host disconnected mid-playback, the in-flight
    video keeps streaming until it ends naturally. New picks
    (`select_video`) are refused; `change_streams` still works
    because the stored token is still valid.
  - `LOCKED` -- no host. Library queries refuse with `423 Locked`,
    Emby-touching events (`select_video`, `change_streams`,
    `report_progress`) refuse.

The grace window between a host's socket dropping and the lock
firing is 5 seconds (`HOST_GRACE_SECONDS`), so a refresh / reconnect
restores the host transparently. See [Flows](#flows) for details.

---

## Connection lifecycle

### `connect` (lifecycle)

Fires automatically when a client opens the WebSocket. The handler:

1. Decodes the `session` cookie for diagnostic logging. **It does
   NOT refuse the connection** even if the cookie is stale or
   absent -- a stale cookie pointing at a deleted party would
   otherwise leave the frontend silently unjoinable. Refusal
   happens later, per-event.
2. Emits `connected` privately to the caller with their `sid`.

The client must follow up with `join_party` to actually bind itself
to a party room.

### `connected` (outbound, `to=sid`)

```js
{ sid: "abc123def456" }
```

Personal handshake acknowledgement. The client stores `sid` so it
can correlate later events.

### `disconnect` (lifecycle)

Fires on socket close. The handler:

1. **Host-leave detection** -- if the departing `client_id` matches
   the party's `host_client_id`, mark `host_left_at = now` and
   schedule `_clear_host_after_grace(party_id, client_id, username)`
   for 5 seconds later. If the same `client_id` rejoins within the
   grace window, the grace task cancels and `host_reclaimed` fires.
2. **Vote cleanup** -- if a late-joiner vote is in progress and the
   departing user is either the joiner or an eligible voter, the
   vote re-evaluates with the smaller eligible set.
3. **Per-user transcode stop** -- reports `Stopped` to Emby and
   stops the user's HLS transcode session.
4. **Members + ready-check cleanup** -- removes the sid from
   `party["users"]`, drops it from any active ready check
   (auto-resolves if the disconnecting user was the only blocker),
   broadcasts `user_left` to the party.

### Reconnect (client responsibility)

`socket.io-client` transparently re-establishes the WebSocket on
transient network drops, but the server has already hard-evicted
the disconnected user per the disconnect handler above. The
reconnected socket has a fresh `sid` and belongs to no party room
until the client re-issues `join_party`.

**The bundled frontend handles this automatically** in
`stores/party.ts`: `setupListeners()` registers a `connect`
listener that re-emits `join_party` with the persistent
`client_id` on every subsequent connect (skipping only the
initial handshake, which `party.join()` covers). Because
`client_id` is stable, the server takes the known-participant
fast path in `join_party` -- state migrates via `_replace_sid`,
no late-joiner vote fires, a fresh `sync_state` is sent to the
reconnected sid.

External socket clients MUST implement the same re-emit on
reconnect or they will silently stop receiving room broadcasts.
The UI hint is up to the implementer; the bundled frontend shows
a "Reconnecting to party..." banner while `connected=false &&
hasEverConnected=true`.

---

## Inbound events (client -> server)

### `join_party`

The client binds itself to a party room after the HTTP join.

```js
socket.emit('join_party', {
  party_id: 'K7N2QF',
  client_id: 'browser-uuid',
  display_name: 'andrew',
  avatar_uuid: 'avatar-uuid',  // optional
})
```

**Behaviour:**

- Joins the Socket.IO room `party_id`.
- If `client_id` is already in `party["participants"]` (a known
  rejoiner), migrates state from the old sid via `_replace_sid`
  (drift strikes, ready-check membership, `user_streams` ownership,
  `current_video.selected_by` if matching, Emby session cleanup
  for the stale stream). **Skips the late-joiner vote** even if
  a video is playing.
- If `client_id` is unknown AND a video is playing AND late-join
  vote is enabled (`LATE_JOIN_VOTE_ENABLED`), starts a vote
  (`join_vote_started` to existing members, `join_vote_pending`
  to the joiner).
- If `MAX_USERS_PER_PARTY` is exceeded, emits `join_rejected` to
  the joiner with `reason: "party_full"` and does not add them.
- On a clean join (no vote, no rejection), emits `user_joined`
  to the room and `sync_state` privately to the new joiner with
  the current playback state.

### `join_vote`

Sent by an existing member to cast their vote in an active
late-joiner vote.

```js
socket.emit('join_vote', {
  party_id: 'K7N2QF',
  vote: 'yes',  // or 'no'
})
```

**Behaviour:**

- Records the vote keyed on `sid` (transient session id, not
  `client_id`). The vote lifetime is bounded by the timeout
  watchdog, so a mid-vote disconnect is handled by
  `_handle_disconnect_from_vote` in the disconnect handler.
- Broadcasts `join_vote_update` with the running tally as
  `{ votes: { username: 'yes' / 'no' }, remaining }` (sids are
  converted to display names before broadcast).
- If a strict majority emerges (yes wins -> vote_pass, no wins ->
  vote_fail), resolves immediately. Pass restarts the video from
  the beginning so the late joiner lands on segment 0. Fail
  emits `join_vote_resolved {result:"fail"}` and `join_rejected`
  to the would-be joiner.
- If everyone has voted but no strict majority was reached (e.g.
  1-1), the selector's vote tiebreaks immediately (no waiting
  for the full timeout). If the selector abstains or is gone,
  the default is `fail`.
- Failed votes set `join_cooldown_until = now + LATE_JOIN_VOTE_COOLDOWN_SECONDS`
  to prevent URL-spam griefing.

### `leave_party`

The user explicitly clicks "Leave Party" (vs just closing the tab,
which fires the implicit disconnect path).

```js
socket.emit('leave_party', { party_id: 'K7N2QF' })
```

Removes the user from the party, stops their transcode, broadcasts
`user_left`, and if they were the host, transitions the lock
immediately (PLAYING-ONLY if a video is active, otherwise LOCKED)
and emits `host_left`. Does NOT honour the 5-second grace window
since the user intentionally left.

### `update_avatar`

The user uploaded a new avatar (or linked a Gravatar) and wants
the rest of the room to re-render with their new image.

```js
socket.emit('update_avatar', {
  party_id: 'K7N2QF',
  avatar_uuid: 'new-avatar-uuid',
})
```

Updates the server-side `participants[client_id].avatar_uuid` and
broadcasts `members_update` to the room. The avatar UUID is a
handle into `/api/avatar/{uuid}` -- the image bytes themselves
ride HTTP, not the socket.

### `select_video`

The selector (any party member at this point -- selector identity
is set on success) picks a video to watch.

```js
socket.emit('select_video', {
  party_id: 'K7N2QF',
  item_id: 'emby-item-id',
  item_name: 'Blade Runner 2049',
  item_overview: '...',
  quality: '1080p-10000',           // optional, defaults to DEFAULT_QUALITY_ID
  media_source_id: 'msid_99999',    // optional, alternate-version pick
})
```

**Auth:** Party must be `UNLOCKED`. `PLAYING-ONLY` refuses with
`error: "Party has no host -- login to become host first"`.

**Side effects:**

- Stores `current_video` with `item_id`, `title`, `overview`,
  `run_time_seconds`, `media_source_id` (resolved version),
  `selected_by` (= sender's `client_id`).
- Stops any previous per-user transcodes via Emby `Stopped` +
  `StopActiveEncodings` calls.
- Resets `playback_state` to `{ playing: false, time: 0 }`.
- Starts a ready check: every member must emit `stream_ready`
  before playback can begin.
- For each party member, creates a fresh per-user transcode
  (own `PlaySessionId`) and emits `video_selected` privately
  with that user's stream URL.
- Broadcasts `ready_check_update` to the room.

### `stop_video`

```js
socket.emit('stop_video', { party_id: 'K7N2QF' })
```

**Auth:** Only the original `selected_by` `client_id` can stop.
Anyone else gets `error: "Only the selector can stop the video"`.

Wipes `current_video`, resets `playback_state`, stops every
per-user transcode, broadcasts `video_stopped` to the room. If the
host was already gone (PLAYING-ONLY), this is the moment the
stored token is cleared and the party fully transitions to
`LOCKED`.

### `change_streams`

A user wants their own audio / subtitle / quality changed mid-playback
without disturbing the rest of the room.

```js
socket.emit('change_streams', {
  party_id: 'K7N2QF',
  audio_index: 0,        // optional
  subtitle_index: -1,    // optional
  quality: '720p-4000',  // optional
})
```

The alternate Emby version (multi-version playback) is locked
party-wide at `select_video` time and stored on
`current_video.media_source_id`; **callers do NOT pass
`media_source_id` here** -- the backend reads it from `current_video`
so every per-user stream stays on the same source for the playback.

**Behaviour:**

- Stops the user's old transcode (Emby `Stopped` + `StopActiveEncodings`).
- Normalises `quality` to a known id, snapshots the party clock,
  fetches fresh playback info from Emby with the new params
  (scoped to the party's `media_source_id`), builds a new HLS URL.
- Emits `streams_changed` PRIVATELY to the caller (`to=sid`) with
  the new stream URL and indices. The rest of the party never
  sees this -- their playback continues uninterrupted.
- Drift correction handles the small (2-5 second) gap while the
  caller's player re-attaches and buffers.

### `play` / `pause`

```js
socket.emit('play',  { party_id: 'K7N2QF', time: 1247.5 })
socket.emit('pause', { party_id: 'K7N2QF', time: 1247.5 })
```

**Selector authority:** the selector's `time` is trusted as the
authoritative party clock. For everyone else, the server overrides
their `time` with its own projection of the party clock and uses
that. (This blocks a non-selector from yanking the party clock
backward/forward by sending a stale time.)

Updates `playback_state`, reports `Unpause`/`Pause` to Emby for
that user's session, and broadcasts `play`/`pause` to the room
with `skip_sid=sid` (the originator's UI already toggled).

### `seek`

```js
socket.emit('seek', {
  party_id: 'K7N2QF',
  time: 1300,
  was_playing: true,
})
```

**Ready-check guard:** seeks are ignored while a ready check is
active. The frontend can fire stray `seeked` events during initial
HLS warmup (frame decode resets `currentTime=0` briefly) and treating
those as real user seeks would cascade 00:00 spam across the party.

**Two-phase behaviour:**

- `was_playing: false` -- simple broadcast: `seek` to the room with
  `skip_sid=sid`.
- `was_playing: true` -- starts a ready check, then in order:
  1. `force_pause_before_seek` to the whole room (UI pauses + shows the buffering overlay).
  2. `ready_check_update` with `waiting=[all members]`.
  3. `seek { time, playing: true, wait_for_ready: true }` to the whole room.

  Each member buffers, emits `stream_ready` when ready, and only
  after everyone has reported ready does the server emit
  `all_ready` to resume.

### `report_progress`

```js
socket.emit('report_progress', {
  party_id: 'K7N2QF',
  time: 1300,
})
```

Sent periodically by the frontend. Reports `TimeUpdate` to Emby
for the user's individual transcode session so Emby's "Continue
Watching" reflects party progress. No broadcast.

### `video_ended`

The user's `<video>` element fired its `ended` event.

```js
socket.emit('video_ended', { party_id: 'K7N2QF' })
```

Fires `Stopped` to Emby (full credit so it stops showing in
Continue Watching), broadcasts `video_ended` to the room (UI
auto-opens the library for the next pick). If the party was in
PLAYING-ONLY, this is also the moment the stored host token is
wiped and the party transitions to LOCKED.

### `stream_ready`

```js
socket.emit('stream_ready', { party_id: 'K7N2QF' })
```

Sent by the frontend after the user's HLS stream finishes
buffering during a ready check. The server tracks ready sids; once
every expected sid has reported ready, it emits `all_ready` with
the current playback state. While the ready check is partially
complete, server emits `ready_check_update` with the
ready/waiting lists.

### `heartbeat`

```js
socket.emit('heartbeat', {
  party_id: 'K7N2QF',
  time: 1247.3,
})
```

Drift detection. Sent every few seconds by every member. Server
compares the reported `time` against its own projection of the
party clock; if drift > 3 seconds for 2 consecutive heartbeats,
emits `drift_correction` privately to the offending sid. The
client seeks to `expected_time` to snap back in line.

### `chat_message`

```js
socket.emit('chat_message', {
  party_id: 'K7N2QF',
  message: 'this is fine 🔥',
})
```

The sender's `username` and `avatar_uuid` are looked up
server-side (the client can't forge them). Broadcasts
`chat_message` to the whole room (including the sender, so
the local UI doesn't have to optimistic-render).

### `toggle_library`

```js
socket.emit('toggle_library', {
  party_id: 'K7N2QF',
  show: true,
})
```

The selector toggled the library panel open / closed. Broadcasts
`toggle_library {show}` to the room so other members see the
library status change in sync (used for the Stop Video ->
library-auto-opens flow).

### `set_binge_watch_active`

Host toggles per-session binge-watch on / off.

```js
socket.emit('set_binge_watch_active', {
  party_id: 'K7N2QF',
  active: true,
})
```

**Auth:** Host-only. Non-hosts get silently ignored (the button
should not have been visible to them). Additionally requires
`BINGE_WATCH_ENABLED=true` in admin config; when the deployment-level
flag is off, the server re-broadcasts `binge_watch_state_changed {
available: false, active: false }` to snap stale UIs back to reality.

**Side effects:**

- Updates `party["binge_watch_active"]`.
- Broadcasts `binge_watch_state_changed { available: true, active }`.
- Turning it off mid-countdown cancels any queued `pending_auto_advance`.

### `auto_advance_cancel`

Anyone in the room hit Cancel on the auto-advance countdown card.

```js
socket.emit('auto_advance_cancel', { party_id: 'K7N2QF' })
```

Cancels the queued advance and broadcasts `auto_advance_cancelled
{ by_username }` to the room. If no advance is pending, this is a
no-op.

---

## Outbound events (server -> client)

### Connection / membership

| Event | Scope | When | Payload |
|---|---|---|---|
| `connected` | `to=sid` | Socket handshake | `{ sid }` |
| `user_joined` | `room` | After successful `join_party` | `{ username, users[], members[] }` |
| `user_left` | `room`, `skip_sid` | After disconnect / leave | `{ username, users[], members[] }` |
| `members_update` | `room` | After avatar / display-name change | `{ members[] }` |
| `sync_state` | `to=sid` | New joiner needs current state | `{ current_video?, playback_state }` |

### Host state

| Event | Scope | When | Payload |
|---|---|---|---|
| `host_changed` | `room` | A member promoted to host via `/api/auth/login` | `{ host_username, host_client_id, is_admin, unlocked: true }` |
| `host_left` | `room` | Host disconnect grace expired OR explicit logout | `{ previous_host, reason, playing_only?: true }` |
| `host_reclaimed` | `room` | Host's `client_id` rejoined within the grace window | `{ host_username }` |

### Playback (party-wide)

| Event | Scope | When | Payload |
|---|---|---|---|
| `video_selected` | `to=sid` (per-user) | A video was picked; each user gets their own stream URL | `{ video: { item_id, title, overview, stream_url, audio_index, subtitle_index, media_source_id, selected_by, quality } }` |
| `streams_changed` | `to=sid` | The caller's `change_streams` produced a new per-user stream | `{ video: {...}, current_time, was_playing }` |
| `video_stopped` | `room` | `stop_video` succeeded | `{ message, stopped_by }` |
| `video_ended` | `room` | A member's player fired `ended` (or a vote-pass restart triggered it) | `{}` |
| `play` | `room`, `skip_sid` | A member hit play | `{ time, username }` |
| `pause` | `room`, `skip_sid` | A member hit pause | `{ time, username }` |
| `seek` | `room`, `skip_sid` (or full room if mid-playback) | A member dragged the scrubber / hit a jump button | `{ time, playing, username, wait_for_ready?: true }` |
| `force_pause_before_seek` | `room` | Mid-playback seek; everyone pauses for the buffering overlay | `{ time }` |

### Sync coordination

| Event | Scope | When | Payload |
|---|---|---|---|
| `ready_check_update` | `room` | A `stream_ready` came in but not everyone's ready yet | `{ ready[], waiting[] }` |
| `all_ready` | `room` | Every expected sid has reported `stream_ready` | `{ time, playing }` |
| `drift_correction` | `to=sid` | Heartbeat showed >3s drift for 2 consecutive cycles | `{ time }` |

### Late-joiner vote

| Event | Scope | When | Payload |
|---|---|---|---|
| `join_vote_started` | `room`, `skip_sid=joiner` | Late joiner triggered a vote | `{ username, timeout_seconds, eligible_voters[], required_majority }` |
| `join_vote_pending` | `to=sid` (the joiner) | The joiner is waiting in the lobby | `{ timeout_seconds, eligible_voters[], required_majority }` |
| `join_vote_update` | `room` | A new vote came in; running tally | `{ votes: { username: 'yes' / 'no' }, remaining }` |
| `join_vote_resolved` | `room` | Vote concluded (pass / fail / cancelled) | `{ result: 'pass' / 'fail' / 'cancelled', reason? }` |
| `join_rejected` | `to=sid` (the joiner) | Vote failed, party was full, cooldown active, or vote already in progress | `{ message, retry_after? }` |

### Binge-watch / auto-advance

| Event | Scope | When | Payload |
|---|---|---|---|
| `binge_watch_state_changed` | `room` | Host toggled the per-session `active` state, or the admin flipped `BINGE_WATCH_ENABLED` for the deployment | `{ available, active }` |
| `auto_advance_pending` | `room` | The current episode ended and the next one is queued -- countdown running | `{ next_item_id, next_title, next_index_number, total_episodes, deadline, countdown_seconds }` |
| `auto_advance_cancelled` | `room` | Anyone in the room hit Cancel on the countdown, OR the admin toggle flipped off mid-countdown, OR host left mid-countdown | `{ by_username: string \| null }` |
| `auto_advance_fired` | `room` | The countdown expired without cancel -- restart of the next episode is happening now | `{ next_item_id, next_title }` |
| `binge_finished` | `room` | End of season (nothing past the current IndexNumber), or the episode had no IndexNumber to advance from | `{ series_id?, season_id?, reason? }` |

### Chat / UI

| Event | Scope | When | Payload |
|---|---|---|---|
| `chat_message` | `room` (incl. sender) | Any member sent a chat message | `{ username, avatar_uuid, message, timestamp }` |
| `toggle_library` | `room` | Selector toggled the library panel | `{ show }` |

### Admin

| Event | Scope | When | Payload |
|---|---|---|---|
| `party_dissolved` | `room` | Admin force-dissolved the party via `/api/admin/...` | `{ reason }` |
| `error` | `to=sid` | Inbound event rejected (not in party, not authorised, etc.) | `{ message }` |

---

## Flows

### Initial join (no video playing)

```
client                          server
  | --- join_party ------------->|
  |                              | binds session -> party room
  |                              | participants[client_id] = {...}
  | <-- sync_state (to=sid) -----|
  | <-- user_joined (room) ------|
```

### Video selection + ready check

```
client (selector)               server                          all clients
  | --- select_video ----------->|
  |                              | stores current_video
  |                              | starts ready check
  |                              | --- video_selected (to=sid) -->| (per user, own stream URL)
  |                              | --- ready_check_update -------->|
  |                                                                |
  |                                                                | (each client buffers, emits stream_ready)
  | <-- stream_ready ------------|
  |                              | --- ready_check_update -------->|
  |                              |    (until all sids ready)
  |                              | --- all_ready ----------------->| (clients hit play)
```

### Mid-playback seek (was_playing: true)

```
client (any)                    server                          all clients
  | --- seek {was_playing:true}->|
  |                              | starts ready check
  |                              | --- force_pause_before_seek --->| (UI pauses + overlay)
  |                              | --- ready_check_update -------->|
  |                              | --- seek {wait_for_ready:true}->| (clients seek + buffer)
  |                                                                |
  |                                                                | (each emits stream_ready when buffered)
  |                              | --- all_ready ----------------->| (everyone resumes)
```

### Late-joiner vote (video already playing)

```
joiner          server                              existing members
  | --- join_party ------------->|
  |                              | new client_id, video active
  |                              | starts vote
  | <-- join_vote_pending -------|
  |                              | --- join_vote_started -------->|
  |                                                               |
  |                                                               | (existing members emit join_vote)
  |                              | <- join_vote (from each)
  |                              | --- join_vote_update --------->|
  |                              |
  |                              | majority reaches:
  |                              | --- join_vote_resolved {pass}->|
  |                              | restarts video from 0
  |                              | --- video_selected (per user)->| (incl. joiner)
  |                              | --- ready_check_update ------->|
```

### Host disconnect + reclaim

```
host                            server                          remaining members
  | (socket drops)               |
  |                              | mark_host_left
  |                              | schedule grace task (5s)
  |                              |
host (refresh)                   |
  | --- join_party ------------->|
  |                              | client_id is host's; _replace_sid
  |                              | grace task -> _try_host_reclaim
  |                              | cancels pending host_left
  |                              | --- host_reclaimed ----------->|
```

### Host disconnect + lock

```
host                            server                          remaining members
  | (socket drops)               |
  |                              | mark_host_left
  |                              | schedule grace task (5s)
  |                              | (5s elapses, no reclaim)
  |                              | clear_host (or keep token if video playing)
  |                              | --- host_left {playing_only?}->|
```

---

## Notes for implementers

- **Always send `party_id` uppercase.** The server normalises it
  on inbound but the rest of the system stores upper-case
  exclusively; lower-case slips will lookup-miss.
- **Selector-only sync authority.** `play`, `pause`, `seek` can
  be emitted by anyone in the party, but only the selector's
  reported `time` is trusted as authoritative. For everyone else
  the server overrides their time with the projected party clock.
  This is why scrubbing should always fire `seek`, not a local
  `currentTime` mutation.
- **Per-user transcodes are silent.** `change_streams` only
  affects the caller's stream URL -- the rest of the party never
  sees a `streams_changed`. Drift correction handles the 2-5s
  gap during HLS re-attach automatically.
- **Ready checks are atomic.** Once a ready check starts, all
  inbound `seek` events are dropped until the check resolves.
  Frontends should suppress stray `seeked` browser events during
  the buffering phase.
- **Vote eligibility snapshots at vote start.** Joining or leaving
  during a vote re-evaluates majority but does not change the
  eligible set (the joiner who can't vote isn't eligible
  themselves; people who leave mid-vote shrink the eligible set
  via the disconnect handler).
- **Host grace is 5 seconds.** A refresh / brief network blip
  preserves host status; a real disconnect collapses to
  PLAYING-ONLY or LOCKED depending on whether a video is in
  flight.
