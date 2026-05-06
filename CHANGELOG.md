# Changelog

All notable changes to Emby Watch Party will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Each release has a short user-facing summary on top and a longer **Technical details** section underneath for anyone who wants the full story.

### Special Thanks
Special thanks to **[QuackMasterDan](https://emby.media/community/index.php?/profile/1658172-quackmasterdan/)** for his dedication in testing and providing valuable feedback throughout development!

Thanks to **[wlowen](https://github.com/wlowen)** and **[JeslynMcKenzie](https://github.com/JeslynMcKenzie)** for testing, detailed bug reports, and providing mediainfo that helped track down the HEVC transcoding issues!

---

## [2.0.0-dev] - Midnight Premiere

This is the working entry for 2.0. The version is `2.0.0-dev` and the branch is `2.0-Rework`. Nothing here has been cut as a stable release yet -- the entry is updated as the rework progresses.

### Added

- **Per-user transcodes**: each user gets their own Emby transcode session and HLS stream, so audio language, subtitle selection, and quality can be different per user without disrupting the rest of the party.
- **Late-joiner vote flow**: when someone tries to join mid-playback, existing users vote on whether to admit them. If the vote passes, the video restarts from the beginning so everyone lands on the same PTS-aligned segment. Vote modal for existing users, waiting-room screen for the joiner. Selector tiebreak on timeout, default-no fallback, 30s cooldown after a failed vote to prevent URL-spam griefing.
- **Silent `change_streams`**: switching audio, subtitle, or quality mid-playback now swaps only your own stream without pausing the rest of the party.
- **Admin panel** (`/admin`) with hot-reload: 17 runtime settings editable from the UI, no restart needed. Two-tier config splits boot-essential `.env` vars from mutable runtime settings persisted to `config.json`.
- **OpenAPI documentation** at `/docs` and `/redoc`. All JSON endpoints have typed Pydantic response schemas so the spec is complete.
- **User guide** ([docs/USER_GUIDE.md](docs/USER_GUIDE.md)) covering the full end-user experience including the vote flow, admin panel, and troubleshooting.
- **Mobile chat panel**: chat slides in over the video on narrow screens with a tap-to-dismiss backdrop. (NewBlade)
- **Reload-as-rejoin**: refreshing the page in an active party is now recognised as a rejoin instead of triggering a vote on yourself. (NewBlade)
- **Library browse position persists across refresh / rejoin / app restart**: drilling into Movies > Action then reloading the page now lands you back in Action with the breadcrumb intact. Saved per-browser in localStorage, falls back to the root if the saved item no longer exists.
- **Library auto-opens on Stop Video**: clicking Stop Video pops the library open in one gesture instead of leaving everyone on a "Browse Library" button. Fires for every user in the party.
- **Codename system**: 2.0 carries the codename "Midnight Premiere", shown on the version page and in the startup banner.

### Changed

- **Full rewrite to FastAPI + Vue 3 + TypeScript**. python-socketio AsyncServer replaces Flask-SocketIO. Vue Router with 6 routes (Index, Party, Login, Admin, Version, 404). Pinia stores for auth/party/socket state. Vite for dev + build. uvicorn replaces gevent as the ASGI server. httpx for async HLS proxying. socket.io-client for real-time sync.
- **Foundation refactor (5 phases)** before the rewrite: introduced `PartyManager`, app-factory pattern with compatibility shims, eliminated string-bool comparisons, merged `run_production.py` into `app.py` as a single entrypoint.
- **Per-user subtitle delivery**: text subtitles via side-channel proxy (`/api/subtitles/...`), image subtitles burned in via per-user transcode. Unified subtitle dropdown shows both with `text` / `burned in` markers in the label. (NewBlade)
- **Selector-only sync authority**: only the user who selected the video can issue play/pause/seek. Non-selector events are silently dropped to prevent state corruption.
- **Admin panel auth**: now Emby-admin-only when login is required, verified via `IsAdministrator` policy from the auth response.

### Fixed

- **Page reload triggered a late-joiner vote** on the user who refreshed. Now recognised as a rejoin via persistent `client_id`. (NewBlade)
- **Default subtitle from Emby** was selected in the dropdown but never actually displayed. Fixed. (NewBlade)
- **Subtitle dropdown hid all text-based subtitles**, leaving only burned-in image subs available. Fixed. (NewBlade)
- **Text subtitle track activation** raced with the `<track>` element's `load` event. Fixed. (NewBlade)
- **Drift correction immediately flagged everyone as several seconds behind** the moment a ready check resolved. Fixed. (NewBlade)
- **Browser pause events fired during seeks** were broadcast to the rest of the party, causing flicker. Now debounced. (NewBlade)
- **Seek events left the server's playing state stale**, causing intermittent state divergence between clients. Fixed. (NewBlade)
- **HLS transcode silently picked stream-copy** over real transcoding for some sources, breaking quality presets. `EnableAutoStreamCopy=false` ported from 1.6.3.
- **Phantom "Andrew seeked to..." chat spam during normal playback** at 5-6 messages per second. Looked like real seeks; was actually Vite HMR stacking duplicate socket listeners across reloads. Fixed by clearing existing listeners before re-registering at every setup point.
- **Subtitle architecture conflict** between HLS.js manifest text tracks and side-channel `<track>` elements (1.6.6 backend + frontend backport). Manifest text-sub params removed from the HLS URL; side-channel proxy is now the single source for text subs. CC menu shows distinct labels for variants like `English (Signs & Songs)`, `English [Forced]`, `English [External]`.
- **CC menu duplicate "Subtitles" entry** when the dropdown's initial-default emit raced the auto-load. Auto-show for the default text sub now happens inside the auto-load watcher so there is no parallel emit to race with.
- **Static session settings required a full restart** to take effect. Toggling "static session = X" via /admin now applies immediately; renaming the id without restart also works.
- **Emoji picker right-side cropping** caused by `.party-content`'s `overflow: hidden` clipping the absolutely-positioned panel. Picker now teleports to `<body>` with computed `position: fixed`, escaping the clip context entirely.
- **Emoji picker scroll jitter** where scrolling the picker shifted it leftward by sub-pixels per wheel tick. Capture-phase scroll listener was firing on the picker's own internal scroll; switched to default-phase so only page-level scroll triggers reposition.

### Removed

- **Old Flask frontend** (`src/`, `static/`, `templates/`, `app.py`). The Vue 3 build at `frontend/` produces static assets served from `backend/static/` so a single uvicorn process serves both.
- **Tracked `config.json`** is now generated from `RuntimeConfig` defaults on first run and gitignored, since values are deployment-specific.

### Contributors

Big thanks to **[NewBlade](https://github.com/NewBlade)** for the comprehensive batch of UX, sync, and reload-handling fixes cherry-picked from his [2.0-Rework fork](https://github.com/NewBlade/emby-watchparty/commits/2.0-Rework/). Author attribution is preserved on every commit.

### Technical details

**Foundation refactor before the rewrite**

Five phases of pre-rewrite work modernised the Flask codebase first so the migration to FastAPI was a transport-layer port rather than a from-scratch rewrite. Phase 1 introduced foundation classes (`PartyManager`, runtime config). Phase 2 wrapped Flask in an app factory with compatibility shims so existing code kept working. Phases 3-4 eliminated string-bool comparisons and migrated callers to the `PartyManager` API. Phase 5 cleaned up dead code and bumped the version to `2.0.0-dev`. By the time `88255e2` swapped the transport, the structural shape of 2.0 already existed.

**FastAPI + Vue 3 rewrite**

Backend replaced Flask + Flask-SocketIO with FastAPI + python-socketio AsyncServer. All routes ported with Pydantic request/response schemas. `FastAPI Depends()` replaces the old `deps` dict pattern. ASGI lifespan handles service initialisation. httpx replaces requests for HLS proxying so streaming is async end-to-end. uvicorn replaces gevent. The `/docs` and `/redoc` endpoints render the auto-generated OpenAPI spec.

Frontend replaced Jinja templates + vanilla JS with Vue 3 + Vite + TypeScript. Vue Router for client-side routing across 6 views. Pinia stores for `auth`, `party`, and `socket` state. socket.io-client for real-time sync. Vite dev proxy forwards backend calls during development; the production build outputs to `backend/static/`.

Docker is now a multi-stage build (node for the frontend, python for the backend) producing a single image.

**Per-user transcodes**

The 1.x model was one shared transcode that everyone read from, with audio/subtitle/quality forced to be uniform. 2.0 creates a fresh `PlaySessionId` per user. Each user picks their own audio track, subtitle, and quality, and the backend builds a separate Emby HLS URL per user. Drift correction was re-added in this model because per-user transcodes can drift independently of each other.

**Late-joiner vote flow**

The fundamental late-joiner problem in per-user transcodes is that Emby rounds `StartTimeTicks` to the nearest keyframe / GOP boundary, so a late joiner's segment 0 starts at a different media position than the party clock. HLS.js trusts what Emby advertises in `#EXT-X-START:TIME-OFFSET`, so `currentTime` reports the "correct" number while the actual frame is 15-20 seconds off. Drift correction can't see this because the late joiner's `currentTime` already equals the party clock.

The solution sidesteps the alignment problem entirely. When a late joiner arrives, existing users vote on whether to admit them. If the vote passes, everyone restarts from `StartTimeTicks=0`, which Emby aligns identically across sessions. Vote eligibility is a snapshot at vote start, strict majority resolves immediately, ties resolve via the video selector at timeout (with default-no fallback if the selector hasn't voted). A 30s cooldown after a failed vote prevents repeated vote pop-ups from a malicious join URL.

**Silent change_streams**

Originally `change_streams` paused the whole party, ran a ready check, and auto-resumed. That was fragile because the target user's resume depended on a coordinated `all_ready` + play broadcast. The flow now:

- Backend snapshots current time, stops the requesting user's old transcode, creates a new one with the up-to-date party position as `StartTimeTicks`, emits `streams_changed` only to the requesting user.
- The party clock is not touched. Other users keep playing. Drift correction continues operating from the authoritative `playback_state` throughout the swap.
- The requesting user's `VideoPlayer` reloads with the new stream URL. Residual lag (typically 2-5 seconds from Emby setup + HLS buffer warmup) is closed by drift correction over the next few heartbeats.
- Stall recovery: if `currentTime` does not advance within 1s after the swap, HLS.js is nudged to reload at the current position.

**Admin panel + two-tier config**

Config splits into `EnvConfig` (frozen, restart required) for boot essentials like bind, port, Emby URL, and login requirement, and `RuntimeConfig` (mutable, hot-reloadable) for everything else (logging, security, session, late-join vote settings). `RuntimeConfig` is persisted to `config.json` and edited via `/admin`.

When `REQUIRE_LOGIN=true` the admin panel requires Emby admin (`IsAdministrator` policy from the auth response). When `REQUIRE_LOGIN=false` it is open for trusted networks. All 17 runtime settings are editable from the UI; the 9 boot-essential settings continue to require a restart and ship in `.env.example`.

**OpenAPI completeness**

Several JSON endpoints had no `response_model`, so the OpenAPI spec emitted empty response schemas and the `/docs` page did not show response structure. New Pydantic schemas: `LibraryItem`, `LibraryItemsResponse`, `ItemDetailsResponse`, `AdminLoginResponse`, `SuccessResponse`, `RuntimeConfigResponse`, `StaticSessionResponse`. Wired up on `/api/libraries`, `/api/items`, `/api/search`, `/api/item/{id}`, `/api/item/{id}/streams`, `/api/admin/{login,logout,config}`, `/api/auth/logout`, `/api/party/static-session`. Binary endpoints (`/api/image`, `/api/subtitles`, `/hls/*`) intentionally stay raw since they return bytes.

**1.6.3 backport: EnableAutoStreamCopy=false**

`build_stream_params` now sets `EnableAutoStreamCopy=false`, `MinSegments=1`, and provides `h264-profile`, `h264-level`, `TranscodeReasons`. PlaybackInfo gained `IsPlayback=true`, `AutoOpenLiveStream=true`, `MaxStreamingBitrate`, `AudioStreamIndex`, `SubtitleStreamIndex`, `MediaSourceId`, `StartTimeTicks`. Without these, Emby would sometimes pick stream-copy for sources that should have been transcoded, breaking quality presets. See [BACKPORT-NOTES.md](BACKPORT-NOTES.md) for the full porting status of 1.6.4 / 1.6.5 / 1.6.6.

**Reload as rejoin via persistent client id (NewBlade)**

A localStorage UUID per browser is sent with `join_party`. The backend tracks `participants[client_id]` separately from the socket-id-keyed `users` dict, so a known client_id reattaching to the room with a fresh socket id is treated as a rejoin and skips the late-joiner vote. The new `_replace_sid` helper migrates all sid-keyed state -- users, join_times, drift_strikes, ready_check sets, `current_video.selected_by`, and `user_streams` ownership including the Emby session cleanup -- in one place. Falls back to legacy username-eviction for clients without a client_id.

**Ready-check clock reset (NewBlade)**

While a ready check was active, wall-clock time elapsed but `playback_state.last_update` did not, so the moment `all_ready` fired the projected time looked N seconds behind reality and drift correction immediately corrected everyone. `_check_all_ready` and the leave/disconnect equivalents now refresh `last_update` at the resolution moment, and the `all_ready` event carries the authoritative `time` + `playing` so clients can seek to the right frame before resuming.

**Native pause debounced during seeks (NewBlade)**

Browsers fire transient pause events during seeks. `onVideoPause` now waits 250ms via `setTimeout`, and `onVideoSeeking` cancels that pending timer, so a pause that's actually part of a seek does not get rebroadcast. `wasPlayingBeforeSeek` was made sticky (`||` instead of `=`) so a sequence of seek events while paused does not clobber the original playing state.

**Unified subtitle dropdown + initial selection (NewBlade)**

The 2.0 dropdown was hiding text subtitles entirely and only showing burned-in image subs. All subtitle tracks now appear in one list with `text` / `burned in` markers in the label. A `selectedBurnedSubtitleIndex()` helper ensures audio/quality changes only carry a subtitle index in the `change_streams` payload when the selection is actually an image sub that needs backend re-encoding; text-sub selections continue to swap via the side-channel proxy without restarting the transcode. `media_source_id` is now part of the `current_video` payload so the subtitle URL builder does not have to guess. When the subtitle list loads with a default from Emby, `applyInitialSubtitleSelection` triggers the same activation flow a manual click would, so the default actually shows instead of just appearing selected. Text track activation now also waits for the `<track>` element's `load` event before setting `mode = 'showing'` to fix the race.

**Mobile chat panel (NewBlade)**

Sliding panel via CSS `transform: translateX(...)` with a backdrop click-to-dismiss, gated by a `showMobileChat` ref and a 760px media query. The header centre section hides on narrow screens to keep room for the chat toggle button.

**Phantom seek spam (HMR socket listener stacking)**

Symptom: chat flooded with "Andrew seeked to 00:01 / 00:02 / 00:03..." 5-6 messages per second during normal playback with no user interaction. The trigger condition narrowed to "happens after picking a subtitle from the dropdown". Several rounds of investigation chased architectural theories -- HLS.js text-track coordination, programmatic `textTrack.mode = 'showing'` triggering native seeks, parent overflow clipping. None of those were the cause.

Actual root cause: Vite HMR was reloading `stores/party.ts` and `views/PartyView.vue` repeatedly across our editing session, and each reload re-ran `setupListeners()` and `onMounted()` which call `socket.on(eventName, handler)` for ~17 different events. Neither setup function ever called `socket.off`, so each HMR cycle stacked another full set of handlers on the same socket.io connection. After ~6 reloads, a single server `seek` broadcast fired its chat-message side effect 6 times.

The math gave it away: with a 500ms debounce on `onVideoSeeked`, the maximum legitimate emit rate is 2 per second. 5-6 messages per second is impossible from one listener. Once spotted, the fix was straightforward: at the top of each setup function, call `socket.off(eventName)` for every event the function is about to register, dropping any previously-bound handlers before re-registering.

Note for future patches: when adding a new `socket.on(...)` in either `stores/party.ts` `setupListeners` or `PartyView.vue` `onMounted`, also add the event name to the corresponding `off()` list at the top so the guarantee keeps holding.

**Subtitle architecture: 1.6.6 backport**

Three pieces of 1.6.6 in 1.x ported to 2.0 to make the dropdown and the browser's CC button drive the same underlying preloaded `<track>` set:

1. *Backend manifest text-sub params removed* from `stream_builder.build_stream_params`. Dropped the unconditional `SubtitleMethod=Hls`, `ManifestSubtitles=vtt`, and the `subtitle_indexes` collection that fed `SubtitleStreamIndexes`. `SubtitleStreamIndex` is now only emitted when an image sub is selected, paired with `SubtitleMethod=Encode` for backend burn-in. Text subs are handled exclusively by the side-channel proxy at `/api/subtitles/<item>/<msid>/<idx>`.
2. *Frontend `onChangeTextSubtitle` rewritten* to find the preloaded `<track>` by URL match and toggle `textTrack.mode` instead of wiping the entire `<track>` set. The dropdown and CC button now perform identical operations on the same preloaded tracks. Falls back to ad-hoc `<track>` creation only when the picked sub is not in the preload set.
3. *1.6.6 label clarity* in the auto-load watcher: `<track>` labels now combine `displayLanguage`, `title`, and `[Forced]` / `[External]` markers so multi-variant releases like "English (Signs & Songs)" / "English (Full)" / "English [SDH]" show as distinct CC menu entries.

The auto-load watcher itself was reworked to skip re-fire when neither `item_id` nor `media_source_id` changed -- a PGS pick triggers `change_streams` which updates `currentVideo` by reference but keeps both ids stable, so re-running the preload would needlessly clear and re-add tracks (and re-show the default), wiping the user's selection. Default text sub is auto-shown only on actual item changes, eliminating a race with the dropdown's initial-selection path that used to leave a stray "Subtitles" entry in the CC menu.

`applyInitialSubtitleSelection` in `VideoControls` is now PGS-only. Image subs need a backend stream restart with `SubtitleMethod=Encode` and that path stays explicit; text-sub auto-show is owned by the auto-load watcher.

HLS.js native text-track features (`subtitleDisplay`, `enableWebVTT`, `renderTextTracksNatively`) are explicitly disabled. Subtitle handling lives entirely outside HLS.js now -- the auto-load watcher manages text-sub `<track>` elements directly, and PGS subs are burned into the video by Emby. HLS.js no longer has any reason to touch textTracks state.

**Library browse position persistence**

A new localStorage key `emby-watchparty-library-state` stores `{ breadcrumbs, parentId }` after every successful `fetchItems` call. Cleared after `fetchLibraries` (root view), so going home wipes the saved state and the next mount starts at the root. Restored in `onMounted` by populating breadcrumbs and calling `fetchItems(savedParentId)`. Stale-state guard: if the saved parent no longer exists in Emby, `fetchItems` returns empty, the component falls back to the root, and the stale state is cleared. Search state is intentionally not saved -- searches reset breadcrumbs and are transient.

**Auto-open library on Stop Video**

A watcher on `party.currentVideo` for non-null -> null transitions sets `showLibrary = true`. Fires for every user in the party because `video_stopped` clears `currentVideo` everywhere. `video_ended` (movie plays to completion) does NOT clear `currentVideo`, only resets `playbackState`, so this does not auto-open at the end of an episode -- intentional, that flow may be auto-binge-watching the next one.

**Emoji picker rework**

Original layout: `position: absolute` inside `.chat-input` inside `.chat-panel` inside `.party-content`. The latter has `overflow: hidden` to contain the side-by-side video + chat layout. Any absolute-positioned descendant of `.party-content` gets clipped at its bounds, so the picker's right side was being chopped off regardless of how wide the panel was made.

Fix: `<Teleport to="body">` + `position: fixed` lifts the panel out of the clip context entirely. Position computed from the trigger button's `getBoundingClientRect()` on open and reapplied on resize / page-scroll. Layout properties (`width`, `max-height`, `overflow`, `box-sizing`, `z-index`, `position`) are set inline rather than via scoped CSS so any Teleport-edge-case where the data-v scope id does not propagate cannot affect them.

The internal scrollbar is hidden entirely (`scrollbar-width: none` for Firefox, `::-webkit-scrollbar { display: none }` for Chromium / Safari). Mouse wheel, touch, and arrow-key scrolling still work natively, but no visible bar consumes the right edge -- the panel reads as visually symmetric on all four sides.

Two bonus improvements added during the rework:
- *Click-outside-to-close*: was missing originally (only re-clicking the trigger would close it).
- *Scroll-listener phase fix*: the resize/scroll repositioning listener originally used capture phase, which caught the picker's OWN internal scroll events too. Each wheel tick re-measured the trigger via `getBoundingClientRect` and re-applied right/bottom, with sub-pixel rounding visible as a leftward jitter while scrolling. Switched to default-phase scroll listener, so only page-level scroll triggers reposition.

**Static session hot-reload**

The admin save endpoint persisted `STATIC_SESSION_ENABLED` and `STATIC_SESSION_ID` to `config.json` and updated the in-memory runtime config, but never told `PartyManager` to actually create the static party in `watch_parties`. Toggling static session ON via /admin would persist the setting but `/party/<id>` returned "Watch party not found" until the next restart -- and even after restart only worked if the user remembered the new id.

`PartyManager` now tracks `_last_static_id` and exposes a new `sync_static_party()` method that reconciles with current config: removes the previous static party if its id no longer matches (rename) or static sessions are now disabled, and creates the configured party if it is missing. The admin handler calls `sync_static_party()` whenever `STATIC_SESSION_ENABLED` or `STATIC_SESSION_ID` is in the changed-fields set, with the party_manager dependency added to the handler signature.

---

### NewBlade contribution outcomes

After porting NewBlade's batch and going through several rounds of testing, here is which commits remain effective in the codebase as of this writing. Author attribution is preserved in git history for all 11 commits regardless of whether the code survived in its original form.

| Commit | Title | Outcome |
|---|---|---|
| `bcafaa6` | Fix text subtitle selection in rework UI | ✅ Active. Briefly reverted in `d0b3380` while phantom seeks were misdiagnosed as a `textTrack.mode` issue, then restored in `3dc96c8` once HMR listener stacking was identified as the real cause. |
| `0ad5b38` | Hide chat panel on narrow screens | ✅ Active. Mobile chat panel unchanged. |
| `4f1f35c` | Preserve playback state across seeks | ✅ Active. Backend `handle_seek` + frontend store `seek` listener both kept verbatim. |
| `acd6467` | Enable selected text subtitle track | ⚠️ Replaced. The wipe-and-replace approach in `onChangeTextSubtitle` was rewritten in `2bd8245` to a find-and-toggle-modes approach that preserves the auto-loaded `<track>` set. Conceptual goal (make the picked text sub actually show) is preserved; the implementation differs. |
| `fdc2ea6` | Fix text track type checks | ⚠️ Dead code. The function the patch targeted was rewritten; the type checks no longer exist in the new code path. |
| `7ffebcf` | Use indexed text track access | ⚠️ Dead code. Same as above -- patched a function that no longer exists. |
| `e6fd406` | Ignore native pause during seek | ✅ Active. 250ms debounce on `onVideoPause` + `wasPlayingBeforeSeek` sticky logic unchanged. |
| `1904e65` | Reset ready check clock on resume | ✅ Active. Backend `last_update` reset + frontend `resumeAfterReadyCheck` payload unchanged. |
| `a2bbb16` | Apply initial subtitle selection | 🔧 Modified. Now PGS-only (`aba43a4`). Text-sub default-show was moved into the auto-load watcher in `PartyView.vue` to eliminate a race where the dropdown's initial emit could reach `onChangeTextSubtitle` before the auto-load had populated the preloaded tracks. |
| `68493ba` | Treat client reloads as participant rejoin | ✅ Active. `client_id`-based rejoin handling unchanged -- the architectural keystone of the whole batch. |
| `3dc006a` | Fix client id UUID generation | ✅ Active. TypeScript cleanup unchanged. |

Net: 7 of 11 commits active as-shipped, 1 modified in scope, 3 superseded by a different implementation of the same goal. The architectural pattern NewBlade introduced -- per-client UUID for rejoin handling, per-user state migration via `_replace_sid`, ready-check clock semantics -- carried through unchanged and forms the structural backbone of how 2.0 handles reload and rejoin.

---

## [1.6.0] - 2026-03-22

### Added
- **Continuous sync / drift correction** ([#13](https://github.com/Oratorian/emby-watchparty/issues/13)): Heartbeat-based system that detects and corrects playback drift. Only corrects the drifted client without disrupting others. Requires 3+ seconds of drift over 2 consecutive heartbeats to avoid false positives
- **Playback action chat messages** ([#22](https://github.com/Oratorian/emby-watchparty/issues/22)): Play, pause, and seek actions now show in chat with the username of who performed them
- **Participant list** ([#23](https://github.com/Oratorian/emby-watchparty/issues/23)): Collapsible participant list in the chat sidebar showing who is currently in the party
- **Autoplay blocked detection**: System message warns users when the browser blocks autoplay and they need to interact with the page

### Fixed
- **Seek resume bug**: Seek events now send the client-side playing state instead of relying on server state, which was stale due to browser pause event ordering during seeks

## [1.5.2] - 2026-03-05

### Fixed
- **SocketIO crash on connect with Flask 3.1+**: `flask-socketio` 5.3.5 set `RequestContext.session` which became a read-only property in Flask 3.1; bumped to >=5.4.0

### Changed
- **Updated dependencies**: flask-socketio 5.3.5 to >=5.4.0

## [1.5.1] - 2026-03-02

### Fixed
- **Regex injection in HLS proxy**: Route parameter `item_id` is now escaped with `re.escape()` before interpolation into regex patterns
- **Reflected XSS in image/subtitle proxy**: Proxy responses now use explicit `flask.Response` objects with whitelisted Content-Type and `X-Content-Type-Options: nosniff` headers
- **DOM XSS in party code input**: Party code is now sanitized to alphanumeric characters and URL-encoded before navigation

### Changed
- **Updated dependencies**: Flask 3.0.0 to >=3.1.3, python-socketio 5.10.0 to 5.14.0, requests 2.31.0 to >=2.32.4

## [1.5.0] - 2026-03-02

### Added
- **Quality selection**: Users can choose stream quality from a dropdown (1080p 10Mbps, 1080p 8Mbps, 720p 4Mbps, 480p 1.5Mbps, 360p 0.5Mbps)
  - Quality is party-wide (shared transcode session), persists across media changes and audio/subtitle switches
  - Late-joining users sync to the current party quality
  - Feature request [#14](https://github.com/Oratorian/emby-watchparty/issues/14) by **[wlowen](https://github.com/wlowen)**
- **Static session mode**: Single persistent party that auto-creates on startup with a fixed ID
  - New `STATIC_SESSION_ENABLED` and `STATIC_SESSION_ID` env vars
  - Users navigating to `/` are redirected straight into the party (no create/join page)
  - Party persists when all users disconnect and is recreated if somehow deleted
  - Useful for home servers with a small group of regulars
  - Feature request [#10](https://github.com/Oratorian/emby-watchparty/issues/10) by **[daniilkopylov](https://github.com/daniilkopylov)**
- **UI collapse toggles**: Collapse header, chat, and video info to maximise video real estate
  - Header collapses to a thin strip with a restore button
  - Chat collapses to a narrow sidebar button, click to expand
  - Video metadata/controls footer can be toggled independently
  - Feature request by **[JeslynMcKenzie](https://github.com/JeslynMcKenzie)**
- **Server-side library pagination**: Library browsing now fetches items in pages instead of all at once
  - Prevents hammering the Emby API with thousands of simultaneous image requests
  - Infinite scroll with sentinel-based loading for seamless browsing
  - `IntersectionObserver` for image lazy loading within scrollable containers
  - Feature request [#15](https://github.com/Oratorian/emby-watchparty/issues/15)
- **Persistent usernames via localStorage**: Returning users skip the username modal and auto-join with their saved name
- **Device profile registration**: WatchParty now registers its codec/container capabilities with Emby on startup for correct transcode behavior
- **Emby dashboard sync on quality change**: Changing quality mid-playback stops the old session and starts a new one so Emby's dashboard reflects the actual transcode settings
- **Version info page**: Dedicated `/version` page showing current version, update check, dependency licenses, credits, and support links
- **Version modal in party view**: Version info accessible from party header without interrupting video playback
- **Codename system**: Each release gets a fun codename (current: "Toasted Pretzel"), shown in startup banner and version page

### Fixed
- **Buffering/stutter with HEVC content**: Non-h264 sources (HEVC, etc.) now transcode to h264 with a 10 Mbps bitrate cap; h264 sources are direct-streamed/remuxed -- Reported by **[wlowen](https://github.com/wlowen)** and **[JeslynMcKenzie](https://github.com/JeslynMcKenzie)**
- **High-bitrate h264 sources causing buffering**: h264 Blu-ray remuxes (e.g. 24 Mbps) now capped at preset bitrate instead of direct-streamed at full bitrate -- Related to [#14](https://github.com/Oratorian/emby-watchparty/issues/14)
- **Video desync on mid-session selection**: Selecting a new video while a session was active caused all clients to start at the previous video's playback position instead of 0:00 -- Reported by **[JeslynMcKenzie](https://github.com/JeslynMcKenzie)**
- **Playback state not reset when switching videos**: Old video's playback session is now properly stopped before starting a new stream -- Reported by **[JeslynMcKenzie](https://github.com/JeslynMcKenzie)**
- **TV Shows button not displaying results**: Client-side display filter only allowed Movie, Episode, and Video types through, silently dropping Series items
- **User count incrementing on page refresh**: Server now evicts stale sessions when the same username rejoins, transferring video control to the new session -- Reported by **[daniilkopylov](https://github.com/daniilkopylov)**
- **Create party button stuck after browser back**: `pageshow` event listener re-enables the button when restored from bfcache -- [#18](https://github.com/Oratorian/emby-watchparty/issues/18) by **[JeslynMcKenzie](https://github.com/JeslynMcKenzie)**
- **Log rotation for socketio.log and access.log**: Reset `_log_rotated` flag before each `setup_logger` call

### Changed
- **Split `party.js` into 7 modules**: Refactored the ~1965-line monolithic file into state, chat, sync, library, video, ui, and a slim party.js orchestrator
- **Split `routes.py` into package**: Refactored ~1150 lines into `src/routes/` with 6 focused modules (pages, auth, library, media, hls, party_api)
- **Split `socket_handlers.py` into package**: Refactored ~940 lines into `src/socket_handlers/` with 7 focused modules (connection, party, playback, sync, chat, quality, updates)
- **Stream capped to 1080p max**: HLS transcode enforces `MaxWidth=1920` and `MaxHeight=1080` -- Reported by **[wlowen](https://github.com/wlowen)**
- **Improved log levels**: Codec detection, transcoding decisions, and token assignment at INFO; silent error paths at WARNING; AUTH CHECK demoted to DEBUG
- **Documentation updated**: README config table, `.env.example`, and `docker-compose.yml.example` now include all env vars

### Removed
- **Dead periodic sync code**: Removed leftover `startPeriodicSync`, `stopPeriodicSync` variables from v1.2

## [1.4.0] - 2026-01-26

### Added
- **APP_PREFIX support for reverse proxy deployments**: Deploy at a URL path prefix (e.g., `/watchparty`)
  - New `APP_PREFIX` config option for path-based reverse proxy setups
  - Uses Flask Blueprint with dynamic url_prefix for native route handling
  - Socket.IO path automatically configured for prefixed deployments
  - All templates and API calls updated to respect prefix
- **Playback progress sync with Emby server**: Watch progress now syncs back to Emby
  - Reports playback start, progress, and stop events to Emby
  - Periodic progress reporting every 10 seconds
  - Resume watching from where you left off on any Emby client
- **Pre-release support in GitHub Actions**: Release workflow now handles alpha/beta/rc versions
  - Auto-detects pre-release tags and sets GitHub release flag accordingly
  - Skips `latest` and `major.minor` Docker tags for pre-releases

### Changed
- **Unified production entrypoint**: Consolidated `run_linux_production.py` and `run_windows_production.py` into single `run_production.py`
  - Both platforms now use gevent, eliminating need for separate files
  - Simpler deployment with single command: `python run_production.py`

### Fixed
- **Session cookie for reverse proxy deployments**: Login now works correctly when using APP_PREFIX behind a reverse proxy
  - Added `SESSION_COOKIE_PATH` configuration to match APP_PREFIX
  - Added `SESSION_COOKIE_SAMESITE='Lax'` for proper redirect handling after login
  - Fixes issue where session cookie wasn't sent with prefixed routes

## [1.3.1] - 2026-01-24

### Fixed
- **Library filtering by user permissions**: Libraries now filtered based on authenticated user's access
  - Feature suggestion by **[Spexor](https://emby.media/community/index.php?/profile/1352631-spexor/)**
  - Uses `/emby/Users/{user_id}/Views` endpoint instead of `/emby/Library/MediaFolders`
  - Restricted users only see libraries they have permission to access
  - Prevents "No items found" errors when clicking inaccessible libraries

## [1.3.0] - 2026-01-23

### Changed
- **Configuration migrated to .env file**: All settings now loaded from `.env` file using python-dotenv
  - Copy `.env.example` to `.env` and configure your settings
  - Old `config.py` values no longer used directly
- **Production server support**: Switched from Werkzeug to gevent for production deployments
  - `run_linux_production.py` for Linux/Docker
  - `run_windows_production.py` for Windows
  - `app.py` no longer runs directly - use platform-specific entry points
- **Rate limiting simplified**: Now accepts numeric values only (e.g., `RATE_LIMIT_API_CALLS=1000`)
  - Time units added automatically (per minute for API calls, per hour for party creation)

### Added
- **LOG_TO_FILE option**: Set to `false` for Docker stdout-only logging
- **GitHub Actions Docker build**: Automatic container builds to ghcr.io on release
- **Version check at startup**: Displays update notification if newer version available

### Fixed
- GitHub version check now actually runs at startup
- Rate limiter configuration error with numeric-only values

### Breaking Changes
- Configuration moved from `config.py` to `.env` file - must migrate settings
- Application must be run via `run_production.py` (unified entrypoint)
- Removed eventlet dependency (deprecated), now uses gevent everywhere

## [1.2.1] - 2025-12-18

### Added
- **Optional Login Gatekeeping**: Authentication system for public deployments
  - Feature idea and contribution by **[MaaHeebTrackbee](https://github.com/MaaHeebTrackbee)**
  - `REQUIRE_LOGIN` config option (default: `false` for backward compatibility)
  - Session-based authentication with configurable expiry (default: 24 hours)
  - Login/logout endpoints with Emby credential validation
  - Clean login UI matching existing theme system
  - Automatic redirect handling when login is disabled
  - Authentication is app-level gatekeeping, not per-user permissions
  - All parties still use configured EMBY_USERNAME/EMBY_PASSWORD for playback
  - Users authenticate with their own Emby credentials for access control
  - Login can be completely disabled (default) for private deployments

### Changed
- **Configuration Storage Pattern**: Boolean configs now store string values
  - `REQUIRE_LOGIN`, `ENABLE_HLS_TOKEN_VALIDATION`, `ENABLE_RATE_LIMITING` store `'true'`/`'false'` strings
  - Boolean comparisons happen in code (`== 'true'`) instead of config files
  - Improves Docker environment variable visibility and debugging
  - Makes actual configured values visible in config object

### Technical
- **Authentication System (src/routes.py):**
  - `@login_required` decorator protects routes when `REQUIRE_LOGIN == 'true'`
  - `/login` route with automatic redirect when login disabled
  - `/api/auth/login` POST endpoint validates credentials via Emby API
  - `/api/auth/logout` POST endpoint clears session
  - `/api/auth/status` GET endpoint returns authentication state
  - Session management with Flask permanent sessions

- **Templates:**
  - `templates/login.html`: New login page with theme support
  - `templates/index.html`: Added conditional logout button

- **Configuration:**
  - `config.py.example`: Added `REQUIRE_LOGIN` and `SESSION_EXPIRY` options
  - `docker-compose.yml.example`: Added login environment variables and clarification comment
  - `app.py`: Added session lifetime configuration

- **Docker Improvements:**
  - `Dockerfile`: Automatic `config.py` creation from `config.py.example` during build
  - `docker-compose.yml.example`: Added comment clarifying config.py requirement
  - Simplified Docker deployment by automating config file setup

- **Boolean Config Refactoring:**
  - Updated all `ENABLE_HLS_TOKEN_VALIDATION` checks in routes.py, socket_handlers.py, utils.py
  - Updated `ENABLE_RATE_LIMITING` check in app.py
  - All boolean configs now compare against `'true'` string

## 1.2.0 - 2025-11-05

### Added
- **Auto Next Episode Feature**: Automatic episode progression for binge-watching
  - Toggle button to enable/disable auto-next (labeled "Auto Next Episode: ON/OFF")
  - 4-second countdown overlay when episode ends showing next episode name
  - Cancel button to stop autoplay during countdown
  - Automatically plays next episode in season when countdown expires
  - Tracks current episode position within season
  - Shows library when reaching end of season
  - Episode metadata now includes IndexNumber, ParentIndexNumber, SeriesId, SeasonId

### Changed
- **Episode API Enhancement**: Backend now returns additional episode metadata
  - Added IndexNumber (episode number), ParentIndexNumber (season number)
  - Added SeriesId and SeasonId for proper episode relationship tracking
  - Enables accurate next episode detection for autoplay feature

- **Major Code Refactoring**: Modular architecture with dependency injection
  - Split monolithic app.py (1913 lines) into clean modular structure
  - New app.py entry point: 161 lines (92% reduction)
  - Replaced custom logger with rsyslog-logger for production-grade logging
  - All components use dependency injection (no global variables)
  - Improved maintainability and testability

- **Logger Replacement**: Switched from custom logger to rsyslog-logger
  - Production-grade logging with proper formatting
  - Structured logs with timestamps and log levels
  - Automatic log rotation (20MB max size, 10 backups)
  - Both console and file output with configurable levels
  - Made debugging significantly easier with clear error messages

### Technical
- **Client-Side (party.js):**
  - New state variables: autoplayEnabled, currentEpisodeList, currentEpisodeIndex, currentSeasonId, currentSeriesId
  - loadSeasonEpisodes() now stores episode list for autoplay tracking
  - selectVideo() tracks current episode index when playing episodes
  - Video 'ended' event handler checks for next episode and triggers countdown
  - startAutoplayCountdown() displays 4-second timer overlay
  - cancelAutoplay() stops countdown and shows library instead
  - hideAutoplayCountdown() removes countdown overlay

- **UI/HTML (party.html):**
  - Added autoplay toggle button in stream controls
  - Added countdown overlay with episode name, timer, and cancel button
  - Countdown initially displays "4" seconds

- **Styling (style.css):**
  - Autoplay toggle button with gradient styling (cyan/purple when ON, grey when OFF)
  - Countdown overlay with blur backdrop and centered content
  - Animated countdown number with pulse effect (5rem font, gradient text)
  - fadeIn animation for smooth countdown appearance
  - Cancel button styling with proper spacing

- **Backend (app.py):**
  - Updated get_items() to include episode-specific fields in API response
  - Fields added to Emby API request: IndexNumber, ParentIndexNumber, SeriesId, SeasonId

- **Architecture Refactoring:**
  - **src/__init__.py**: Package initialization with version tracking
  - **src/emby_client.py** (240 lines): EmbyClient class encapsulates all Emby API interactions
    - Logger injected as constructor parameter for testability
    - Methods: authenticate, fetch libraries, get item details, playback info, transcoding cleanup
  - **src/party_manager.py** (145 lines): PartyManager class for state management
    - Replaces global watch_parties and hls_tokens dictionaries
    - Methods: create_party, get_party, update_party, cleanup
  - **src/utils.py** (190 lines): Helper functions with dependency injection
    - generate_random_username, generate_party_code, generate_hls_token
    - validate_hls_token, get_user_token
    - All functions accept dependencies as parameters (no globals)
  - **src/routes.py** (848 lines): All Flask HTTP routes
    - init_routes() function wraps all route definitions
    - Dependency injection: app, emby_client, party_manager, config, logger
    - Routes import utilities and access party state via party_manager
  - **src/socket_handlers.py** (624 lines): All SocketIO event handlers
    - init_socket_handlers() function wraps all handlers
    - Dependency injection: socketio, emby_client, party_manager, config, logger
    - Handlers import utilities and access party state via party_manager
  - **app.py** (161 lines): Clean entry point with dependency injection
    - Initializes rsyslog-logger, EmbyClient, PartyManager
    - Calls init_routes() and init_socket_handlers() with injected dependencies
    - Reduced from 1913 lines (92% reduction)

- **Dependency Injection Fixes:**
  - Fixed generate_party_code() missing watch_parties parameter
  - Fixed get_user_token() calls missing hls_tokens, config, logger parameters
  - Fixed validate_hls_token() calls missing hls_tokens, watch_parties, config, logger, item_id
  - Replaced all EMBY_SERVER_URL references with config.EMBY_SERVER_URL
  - Replaced all EMBY_API_KEY references with emby_client.api_key

- **rsyslog-logger Integration:**
  - Replaced custom logger with rsyslog-logger package (user's own package)
  - Setup: name="emby-watchparty", log_file="logs/emby-watchparty.log", log_level="INFO"
  - Format: "rsyslog" with structured timestamps and log levels
  - Rotation: max_size=20MB, backup_count=10
  - Console and file output with independent log level control
  - Made debugging significantly easier with clear structured error messages

## 1.1.1 - 2025-10-30

### Added
- **Multi-Theme System**: 6 chooseable themes with localStorage persistence
  - Cyberpunk Theater (default with neon cyan/magenta accents)
  - Material Random (infinite random gradient combinations from Material Design palette)
  - Emby Green (inspired by Emby's signature green colors)
  - Classic Dark (professional dark mode)
  - Minimal Light (soft grey backgrounds, easy on eyes)
  - Netflix Red (streaming service aesthetic)
  - Theme selector with emoji icons on both index and party pages
  - Dedicated [theme.js](static/js/theme.js) module for theme management
  - Automatic theme persistence across sessions

- **Material Random Theme**: JavaScript-powered infinite color variations
  - 20 Material Design colors creating 152,000+ possible combinations
  - Randomize button (🎲) appears when Material theme is selected
  - Generates random gradients for primary/secondary/accent/gold colors
  - Real-time CSS custom property injection
  - Automatic style cleanup when switching to other themes

- **WhatsApp-Style Chat Interface**: Modern messaging design
  - Messages from others aligned left with tertiary background
  - User's own messages aligned right with gradient bubble
  - Rounded chat bubbles (12px radius) with proper shadows
  - Username display in each message bubble
  - Flexbox-based responsive layout (70% max-width bubbles)
  - Different bubble tail styles (bottom-left vs bottom-right)

- **Theater Media Center Aesthetic**: Cinema-inspired visual design
  - Gold theater borders around video player (3px solid)
  - Red curtain outline effect (8px rgba outline-offset)
  - Marquee-style header with gradient top border
  - Cinema emojis throughout UI (🎬 🎭 🎞️ 💬)
  - Spotlight shadow effects and glow on interactive elements
  - Inset shadows for depth and dimension on containers

- **Video End Detection**: Automatic library showing when playback finishes
  - Detects natural video end via HTML5 'ended' event
  - Automatically shows library sidebar for all party members
  - Perfect for anime binge-watching workflow
  - System message in chat: "🎬 Video ended - Ready for next episode"
  - Server broadcasts `video_ended` event via Socket.IO

- **Auto-Exit Fullscreen on End**: Smooth transition after video playback
  - Automatically exits fullscreen when video ends naturally
  - Cross-browser support (Chrome, Firefox, Safari, Edge)
  - Uses all vendor-prefixed fullscreen APIs
  - Prevents users being stuck in fullscreen after completion

- **Library Selection Persistence**: Navigation state survives page refreshes
  - Saves current library/show/season selection to localStorage
  - Automatically restores last browsing position on page reload
  - Tracks three navigation levels: library items, season list, episode list
  - Stores IDs and names for accurate restoration
  - Graceful fallback to library root if saved state is invalid
  - Perfect for when page refreshes are needed during browsing

### Changed
- **Fullscreen Border Removal**: JavaScript-based solution for reliability
  - CSS pseudo-selectors (`:fullscreen`) weren't working across all browsers
  - JavaScript event listeners detect fullscreen state changes
  - Inline styles force border/outline/shadow removal (highest CSS specificity)
  - All decorative elements (borders, shadows, outlines) hidden in fullscreen
  - Normal styles automatically restored when exiting fullscreen
  - Cross-browser event support (fullscreenchange, webkitfullscreenchange, etc.)

### Fixed
- **Playback State Reset on Video End**: Prevent position carry-over to next video
  - Video 'ended' event now resets currentPartyState and playbackStartTime on client
  - Server resets playback_state to `{playing: false, time: 0}` when video ends
  - Fixes issue where seek position from previous video carried over to next selection
  - Each new video starts with clean playback state
  - Prevents confusing behavior when selecting episodes back-to-back

### Technical
- **Client-Side (party.js):**
  - Library state persistence functions: saveLibraryState(), getSavedLibraryState(), clearLibraryState()
  - restoreLibraryState() function called on party join to restore browsing position
  - saveLibraryState() in loadItemsFromLibrary(), loadSeriesSeasons(), loadSeasonEpisodes()
  - clearLibraryState() when returning to library root
  - Fullscreen event listeners for all browser prefixes (fullscreenchange, webkitfullscreenchange, etc.)
  - handleFullscreenChange() function applies/removes inline styles for border removal
  - Video 'ended' event handler with state reset and automatic fullscreen exit
  - currentPartyState and playbackStartTime reset to null on video end

- **Server-Side (app.py):**
  - handle_video_ended() Socket.IO event handler
  - Reset playback_state to `{playing: false, time: 0}` on video end
  - Broadcast video_ended event to all users in party room

- **Theme System (theme.js):**
  - Material Design color palette array with 20 vibrant colors
  - generateMaterialGradient() creates random color combinations (152,000+ possibilities)
  - applyMaterialGradients() sets CSS custom properties via inline styles
  - clearMaterialStyles() removes inline properties when switching themes
  - Randomize button dynamically shows/hides based on selected theme
  - Theme selector event listeners synchronized across all dropdown instances

- **UI/CSS (style.css):**
  - 6 complete theme definitions using CSS custom properties
  - WhatsApp-style chat bubble layout with flexbox alignment
  - Theater aesthetic with gold borders, red curtain effects, cinema emojis
  - Fullscreen CSS rules with !important (backup for JavaScript solution)
  - Material Design elevation shadows (2dp, 4dp, 8dp)

## [1.1.0] - 2025-10-25

### Added
- **Skip Intro Button**: Interactive button to skip intro sequences
  - Appears when intro markers are detected in Emby metadata
  - Positioned above video controls for easy access
  - Automatically shows/hides based on current playback position
  - Only works in normal viewing mode (limitation: not visible in fullscreen due to HTML5 video fullscreen constraints)
  - Synced across all party members when clicked
  - **Note:** Requires Emby API key to be configured for intro marker detection

- **Intelligent PGS Subtitle Handling**: Smart detection and burn-in for image-based subtitles
  - Automatically detects PGS (Presentation Graphic Stream) subtitles
  - Burns in PGS/VobSub/DVD subtitles for pixel-perfect quality
  - Supports: pgssub, pgs, dvd_subtitle, dvdsub, vobsub formats
  - Prevents quality loss from PGS-to-text conversion
  - Works on both GPU and software encoding setups
  - PGS subtitles marked with [Burned-in] indicator in dropdown

- **Independent VTT Subtitle Selection**: Per-user subtitle language choice
  - All text-based subtitles automatically loaded as WebVTT tracks
  - Each party member can independently choose their subtitle language
  - Uses native browser CC button for subtitle selection
  - No transcode restarts needed for VTT subtitle changes
  - Subtitle dropdown automatically hides when only VTT subtitles available
  - PGS subtitles remain synced (burned-in), VTT selection is local-only

### Changed
- **Subtitle Workflow**: Dual-mode subtitle handling
  - PGS subtitles: Server-side burn-in with `SubtitleMethod=Encode` (synced for all users)
  - Text subtitles: Client-side VTT loading with independent selection (local per user)
  - Subtitle dropdown now only shows PGS options when available
  - Audio selection remains synced across all party members (requires transcode)

- **Multi-Audio Track Support**: Re-enabled audio track selection
  - Added back `AudioStreamIndex` parameter for proper audio track selection
  - Users can now switch between multiple audio tracks (e.g., different languages)
  - Audio track changes are synced across all party members
  - Fixes issue where only default audio track was available

- **Sync Architecture Overhaul**: Removed periodic sync workaround
  - Disabled 5-second periodic sync check (added in v1.0.5, no longer needed)
  - Server now calculates accurate current time for new joiners
  - Client compensates for network and loading delays
  - Sync accuracy improved from ±4 seconds to sub-second precision
  - Simpler, more reliable sync mechanism

### Fixed
- **Mid-Play Join Sync Issues**: Complete overhaul of new joiner sync behavior
  - Fixed video restarting to 0:00 for existing users when someone joins
  - New joiners now start at correct position (e.g., 22 minutes, not 0:00)
  - New joiners can immediately receive play/pause/seek commands
  - Set isSyncing flag before loadVideo() to prevent MANIFEST_PARSED reset
  - Use HLS.js startPosition config to load correct video segments immediately
  - Clear isSyncing in MANIFEST_PARSED to allow command processing
  - Server calculates elapsed time since last play/pause/seek for accurate sync
  - Client compensates for network + metadata loading delay (0.1-0.5s typical)
  - Loading delay compensation capped at 2 seconds to prevent over-compensation

- **False Drift Detection**: Eliminated random seeking and desyncing
  - Periodic sync was detecting false "drift" after pause/play
  - Example: Pause at 496s, play again → periodic sync thought 5s drift existed
  - Removed periodic sync - play/pause/seek events provide sufficient sync
  - No more random video forwarding or seeking
  - Pause/play now works smoothly without desyncing users

- **Subtitle Filtering and Sync Issues**: Resolved subtitle-related sync loop bug
  - Fixed issue where mid-play joiners caused sync loops
  - Improved subtitle stream filtering logic
  - Better handling of default/forced subtitle selection
  - Removed invalid `SubtitleMethod=Drop` parameter (doesn't exist in Emby API)
  - Fixed PGS subtitles appearing by default when "None" selected
  - Omit subtitle parameters entirely when None selected to prevent Emby auto-selection

- **UI Layout Issues**: Fixed spacing and layout problems
  - Clear all subtitle tracks from video element when changing videos (prevents CC button clutter)
  - Fixed Stop Video button stretching with `flex: 0 0 auto`
  - Changed subtitle container visibility from `display` to `visibility` toggle
  - Prevents Audio and Stop Video button from squishing together
  - Added max-width to stream controls for consistent spacing
  - Proper button positioning with `.stop-button-group` class

### Technical
- **Server-Side (app.py):**
  - Calculate accurate current time when new user joins (handle_join_party)
  - Add elapsed time since last_update to playback_state.time for playing videos
  - Send compensated time to new joiners: `current_time = stored_time + elapsed`
  - Added debug logging for new joiner sync calculations

- **Client-Side (party.js):**
  - Capture sync_state arrival time for delay compensation
  - Set playbackStartTime when new joiner starts playing
  - Disabled periodic sync (removed from play handler and sync_state handler)
  - Improved periodic sync guards (check both party state and video state)
  - Enhanced subtitle stream detection with `isPGS` flag
  - Automatic text track cleanup in `loadAllTextSubtitles()` function
  - Modified subtitle dropdown event listener to only emit party sync for PGS subtitles

- **Code Cleanup:**
  - Removed 3 unused variables (lastSyncTime, lastSeekBroadcast, seekBroadcastDelay)
  - Removed empty socket.on('connected') handler
  - Removed 12 development console.log statements
  - Reduced party.js from 1493 to 1459 lines (34 lines saved)
  - Fixed syntax error (extra closing brace in subtitle change handler)

## [1.0.6] - 2025-10-24

### Fixed
- **Critical Audio Fix**: Videos now play with audio correctly
  - Added `AudioCodec=aac,mp3` parameter to force compatible audio transcoding
  - Added `TranscodingMaxAudioChannels=2` and `MaxAudioChannels=2` to ensure audio inclusion
  - Removed `AudioStreamIndex` parameter that was causing Emby to strip audio
  - Fixes issue where videos with FLAC or other lossless audio codecs had no sound
  - **Dolby TrueHD support**: Now properly downmixes and transcodes to stereo AAC/MP3
  - HLS streams now properly transcode audio to browser-compatible formats

- **Video Looping Fix**: Videos no longer loop after 2-4 seconds
  - Added `BreakOnNonKeyFrames=True` to allow proper HLS segment generation
  - Added `VideoCodec=h264` to ensure maximum browser compatibility
  - Fixes issue where videos would play 2-4 seconds then restart
  - Works with both HEVC (H.265) and AVC (H.264) source videos

### Changed
- **Unified Transcoding Profile**: All clients receive same quality stream
  - Video: H.264 (maximum compatibility, works on all browsers)
  - Audio: AAC or MP3 (handles FLAC, TrueHD, DTS, AC3, etc.)
  - Channels: Downmixed to stereo (2.0) from any multi-channel format
  - Single transcode per party = better performance and perfect sync

- **Enhanced HLS Parameters**:
  - `AudioCodec=aac,mp3` - Supports both AAC and MP3 fallback
  - `VideoCodec=h264` - Force H.264 for universal browser support
  - `BreakOnNonKeyFrames=True` - Allow seeking to any point in video
  - `MaxAudioChannels=2` - Downmix surround sound to stereo

### Technical
- Modified HLS URL generation in `select_video` and `change_streams` handlers
- Added debug logging for HLS master playlist content
- Enhanced audio stream handling to prevent transcoding issues
- Optimized for "lowest common denominator" approach (single transcode for all clients)

## [1.0.5] - 2025-10-23

### Added
- **Periodic Sync Check**: Automatic drift correction every 5 seconds
  - New `startPeriodicSync()` function monitors playback timing
  - Automatically corrects sync drift greater than 0.3 seconds
  - Only syncs during active playback (skips when paused or seeking)
  - Stops when video is stopped to conserve resources
- **Browser Compatibility Documentation**: Added detailed browser support section to README
  - Desktop browser compatibility (Chrome, Edge, Firefox, Safari, Brave)
  - Mobile browser compatibility with specific iOS/Android recommendations
  - Known issues section for Brave iOS subtitle limitation

### Changed
- **Improved Invite Codes**: Simplified party code format for easier communication
  - Changed from 10-12 character URL-safe tokens to simple 5-character codes
  - Uses uppercase letters and numbers only (A-Z, 2-9)
  - Excludes confusing characters (0, O, 1, I, L) for clarity
  - Examples: `A3B7K`, `N2YS2`, `Y5HYP` instead of `abc123XyZ9aBc1`
  - Much easier to communicate over phone or in person
- **Tighter Sync Threshold**: Reduced from 0.5s to 0.3s for better accuracy
  - Fixed misleading comment (was "2 seconds" but code was 0.5s)
  - More accurate synchronization between players
  - Reduces typical sync offset from ~4 seconds to under 0.3 seconds
- **Better Browser Reload Handling**: Improved sync behavior when users refresh
  - Changed condition from `time > 1` to `time >= 0`
  - Now syncs correctly at any video timestamp, including beginning
  - Starts periodic sync check immediately after reload

### Fixed
- **Sync Timing Issues**: Addressed offset between players after seeking or reloading
  - Periodic sync check prevents drift accumulation over time
  - Browser reloads now sync correctly regardless of video position
  - Seeking and leaving/reloading no longer causes 4-second desync
- **State Tracking**: Enhanced playback state management
  - Added `currentPartyState` variable to track server's authoritative state
  - Updated on every play/pause/seek event from server
  - Used by periodic sync to detect and correct drift

### Documentation
- Added browser compatibility matrix for desktop and mobile
- Added known issues section for Brave iOS subtitle limitation
- Documented recommended browsers for different platforms
- Updated party code format in features list

## [1.0.4] - 2025-10-22

### Added
- **External Subtitle Support**: Major improvement to subtitle handling
  - New subtitle proxy endpoint `/api/subtitles/<item_id>/<media_source_id>/<index>` for serving WebVTT files
  - HTML5 `<track>` element integration for native browser subtitle rendering
  - `loadSubtitleTrack()` function for dynamic subtitle loading in frontend
  - `isTextSubtitleStream` flag in streams API response
  - `media_source_id` tracking across video selection and stream changes
- **Transcoding Cleanup**: Automatic cleanup of Emby HLS transcoding sessions
  - `stop_active_encodings()` method in EmbyClient
  - Calls DELETE `/Videos/ActiveEncodings` when video stops or changes
  - Prevents abandoned transcoding processes from consuming server resources

### Changed
- **Subtitle Delivery Method**: Switched from burned-in to external subtitles
  - Removed `SubtitleMethod` parameter from HLS URLs
  - Subtitles now load as separate WebVTT files instead of being encoded into video
  - Enables instant subtitle switching without video reload
- **UI Layout Redesign**: Compact video controls layout
  - Video description and stream controls now displayed side-by-side
  - Audio, Subtitles, and Stop Video button placed in single horizontal row
  - Video description reduced to 2-line clamp for space efficiency
  - Added invisible label to Stop Video button for proper vertical alignment
  - Improved responsive flex layout for stream controls

### Fixed
- **Subtitle Timeout Issues**: Resolved 502 Bad Gateway errors on complex subtitle files
  - Complex ASS/SSA subtitle files (e.g., "The Apothecary Diaries") no longer cause timeouts
  - Emby no longer forced to burn subtitles into video stream during transcoding
  - Significantly reduced CPU load during playback with subtitles
- **Resource Management**: Proper cleanup of server resources
  - HLS transcoding sessions now properly terminated when playback ends
  - Prevents memory and CPU waste from abandoned encoding processes

### Technical
- Frontend subtitle track management with proper cleanup and replacement
- Media source ID propagation through `video_selected`, `streams_changed`, and `sync_state` events
- Enhanced stream metadata with text subtitle stream detection

## [1.0.3] - 2025-10-21

### Added
- **Stop Video Button**: Allows the user who selected a video to stop it for all party members
  - Only visible to the video selector
  - Clears video player for all users
  - Backend validates only the selector can stop the video
- **HLS Token Validation System**: New security layer for HLS stream access
  - Per-user HLS tokens tied to socket session IDs
  - Token expiry tracking and automatic cleanup
  - Each user gets their own unique token for stream access
  - Prevents direct stream access bypass
- **Comprehensive Debug Logging**: Enhanced debugging capabilities
  - Detailed debug logs for token generation and validation
  - Playlist URL rewriting visibility
  - Token assignment tracking per user
  - Comprehensive error reporting with full context (error type, URLs, tracebacks)
  - Separate error handling for network errors vs internal errors
- **Configuration Template**: Added `config.py.example` for easier setup
  - `config.py` is now untracked to prevent committing credentials
  - Users copy `config.py.example` to `config.py` and configure

### Changed
- **Library Sidebar Behavior**: Improved UI consistency
  - Library sidebar now hides for ALL users when video is selected (not just selector)
  - Library sidebar automatically reopens when video is stopped
  - Consistent UI state across all party members
- **Rate Limiting**: Increased default API rate limit to 1000 requests/minute (from 100)

### Fixed
- Token URL parameter construction now uses proper separator detection (& vs ?)
- Tokens correctly appended to ALL playlist types including `main.m3u8`

### Security
- Per-user HLS tokens with session validation
- Token expiry tracking and cleanup
- Rate limiting configuration improvements
- Tokens properly tied to socket session IDs for validation

## [1.0.2] - 2025-10-20

### Fixed
- Clean up chat system messages and fix username display
  - Remove verbose system messages (track counts, HLS ready, video loaded)
  - Change message format from "selected:" to "selected" for cleaner display
  - Fix username variable not being set when server generates random username
  - Keep only essential messages: user selections and critical errors
  - Auto-capture username from server on join event

### Changed
- Chat only shows relevant user actions instead of technical status updates

## [1.0.1] - 2025-10-20

### Added
- **Secure HLS Proxy**: Major security improvement
  - Implement lightweight HLS proxy endpoints for master playlists and segments
  - Add URL rewriting to redirect playlist requests through Flask proxy
  - Only Flask app needs to be exposed, Emby stays on local network
  - Security improvement: Emby server no longer needs internet exposure

### Fixed
- Fixed syntax error in `party.js:529` (extra closing brace, missing `)`)

### Documentation
- Updated README with note about Emby remote access no longer being required
- Clarified that only the Flask app needs to be exposed to the internet

## [1.0.0] - 2025-10-20

### Added
- **Initial Release**: First public version of Emby Watch Party
- **Core Features**:
  - Create and join watch parties with shareable party codes
  - Synchronized video playback across all party members
  - Real-time chat functionality
  - Video library browsing and search
  - Season and episode selection for TV shows
  - Audio and subtitle track selection
  - Automatic playback synchronization
  - Random username generation for guests
- **Media Server Integration**:
  - Direct integration with Emby media server
  - HLS streaming support with quality selection
  - Support for movies and TV shows
  - Direct transcoding through Emby
- **User Interface**:
  - Clean, modern web interface
  - Responsive design for desktop and mobile
  - Library sidebar with search
  - Video player with full controls
  - Chat panel with drag-to-resize
  - System messages for user actions
- **Technical Features**:
  - Flask backend with Socket.IO for real-time communication
  - HLS.js for adaptive bitrate streaming
  - Session-based party management
  - Custom logging system with rotation
  - Environment variable configuration

### Documentation
- Comprehensive README with setup instructions
- Installation guide with dependencies
- Configuration documentation
- Development setup instructions

---

## Version History Summary

- **v1.0.6** (2025-10-24): Critical audio fix - videos now play with sound
- **v1.0.5** (2025-10-23): Simplified invite codes, improved sync timing, browser compatibility docs
- **v1.0.4** (2025-10-22): External subtitle support, transcoding cleanup, UI layout improvements
- **v1.0.3** (2025-10-21): Stop video feature, HLS token validation, enhanced debugging
- **v1.0.2** (2025-10-20): Chat cleanup and username fixes
- **v1.0.1** (2025-10-20): Secure HLS proxy, Emby stays internal
- **v1.0.0** (2025-10-20): Initial release with core watch party features

---

## Links

- **Repository**: https://github.com/Oratorian/emby-watchparty
- **Issues**: https://github.com/Oratorian/emby-watchparty/issues
- **Releases**: https://github.com/Oratorian/emby-watchparty/releases

---

## Educational Use Notice

This project is intended for educational purposes and private use only. Please ensure you use this responsibly and in compliance with your Emby server's terms of service and applicable copyright laws.
