# Changelog

All notable changes to Emby Watch Party will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Each release has a short user-facing summary on top and a longer **Technical details** section underneath for anyone who wants the full story.

### Special Thanks
Special thanks to **[QuackMasterDan](https://emby.media/community/index.php?/profile/1658172-quackmasterdan/)** for his dedication in testing and providing valuable feedback throughout development!

Thanks to **[wlowen](https://github.com/wlowen)** and **[JeslynMcKenzie](https://github.com/JeslynMcKenzie)** for testing, detailed bug reports, and providing mediainfo that helped track down the HEVC transcoding issues!

Thanks to **[Christian Gillinger](https://github.com/cgillinger)** for the "Refined Cyber" design language that the 2.0 visual refresh is built on -- the cyan/magenta/violet palette, glass surface treatment, chip/pill control language, animated LIVE badge, and centred system-message pill in chat all come from his mockup.

---

## [2.0.0-dev] - Midnight Premiere

2.0 is a top-to-bottom rewrite of Emby Watch Party. The 1.x line was a Flask app with Jinja templates, vanilla JS on the frontend, and a single shared Emby transcode that the whole party watched in lockstep: one stream URL, one audio track, one subtitle, one quality. It worked, but the architecture made every "can I have my own subtitles", "can I lower my quality on hotel wifi", "why am I stuck on Japanese audio because someone else picked it" request a structural impossibility.

2.0 starts over on three foundations:

- **FastAPI + Vue 3 + TypeScript** replaces Flask + Jinja + vanilla JS. Async end-to-end, typed Pydantic schemas with auto-generated OpenAPI docs at `/docs` and `/redoc`, Pinia stores, Vue Router, Vite for dev + build. A single uvicorn process serves the backend and the compiled frontend from the same Docker image.
- **Per-user transcodes**. Each user gets their own `PlaySessionId` and their own Emby HLS stream. Audio track, subtitle, and quality are now personal settings that can be changed mid-playback without pausing the rest of the party. Drift correction was re-added to keep these independent streams in sync against the authoritative party clock.
- **Late-joiner vote flow**. Per-user transcodes break the old "everyone gets the same Emby segments" guarantee, so late joiners can no longer be slotted in mid-playback without keyframe misalignment. Existing users now vote on whether to admit a late joiner; if the vote passes, the video restarts from the beginning so every session lands on PTS-aligned segment 0.

Around those pillars: an admin panel at `/admin` with 17 hot-reloadable runtime settings, a unified subtitle dropdown that handles text subs (side-channel proxy) and image subs (burned-in transcode) in the same UI, a mobile chat slide-over, reload-as-rejoin via persistent `client_id`, library browse-position persistence, and a codename system. See the **[project wiki](https://github.com/Oratorian/emby-watchparty/wiki)** for the full end-user walk-through.

Codename: **Midnight Premiere**. Branch: `2.0-Rework`. The version is `2.0.0-dev` while in active development; closed-beta images are tagged `2.0.0-betaN` on GHCR. This entry is updated as the rework progresses and will be finalised when 2.0.0 is cut.

### Breaking Changes (cumulative across the 2.0 dev cycle)

- **`EMBY_USERNAME` and `EMBY_PASSWORD` are no longer read from `.env`.** Per-user Emby authentication is now an in-app action: any party member clicks "Login to Become Host" inside the party and supplies their own Emby credentials. The backend never stores long-lived user credentials at rest; only the admin server key (`EMBY_API_KEY`) remains in env. Existing deployments must remove these two lines from `.env` before upgrading.
- **`REQUIRE_LOGIN` semantics changed** ([#31](https://github.com/Oratorian/emby-watchparty/issues/31)). The setting now gates only party CREATION:
  - `false` (default): anyone can create a party. Spectators join with just the code. Any member can later click "Login to Become Host" to unlock the library for everyone in the room. Browsing always requires a host with a valid Emby session.
  - `true`: party creation requires Emby credentials in the request body; the creator becomes host atomically. Spectators still join with just the code, no Emby login prompt.
  - The setting also moved from `.env` to `config.json` -- it's now a runtime admin-panel toggle, hot-reloadable.
- **Backend HTTP endpoints now require a party-bound session cookie.** `/api/libraries`, `/api/items`, `/api/search`, `/api/item/<id>...`, `/api/intro`, `/api/image`, `/api/subtitles`, and `/hls/...` all return `401` without a session and `423 Locked` when the party has no host. The frontend obtains the cookie automatically via the new `POST /api/party/<id>/join` step before the socket connection.
- **`POST /api/party/create` request body changed.** Anonymous create with `REQUIRE_LOGIN=false` accepts an empty body or just `{ client_id }`. With `REQUIRE_LOGIN=true`, the body now requires `{ client_id, display_name, username, password }`.
- **`/api/auth/login` is now "become host of your current party"**, not a global login. Requires a party-bound session cookie. Body is `{ username, password }`; on success the caller is recorded as host and the room sees a `host_changed` socket event.
- **Frontend `/login` route removed.** The global LoginView is gone; logging in as host happens inside a party via the "Login to Become Host" button.
- **`current_video.selected_by` is now a client_id, not a sid.** Selector identity now survives reloads and brief reconnects without re-electing on a fresh sid.

### Release history

Closed-beta builds tagged on GHCR. The version stays `2.0.0-dev` while in active development; each beta below carries only the bullets new to that build. The **Breaking Changes** above and the **Technical details** further down apply to the dev cycle as a whole, not to any individual beta.

#### [2.0.0-beta12] - 2026-06-20 - A-Z library jump bar

##### Added

- **iOS-style A-Z jump bar** to the library browser. A column of `#` + `A` through `Z` buttons renders to the right of the items grid whenever the loaded list has at least 30 items (short folders / seasons stay clean). Letters with no matching items are dim and not clickable; letters that do have matches glow cyan on hover. **Left-click** scrolls the grid to the first item whose name starts with that letter (`scrollIntoView({ behavior: 'smooth' })`). **Right-click** toggles a filter that hides every card except the ones starting with that letter; right-click the same letter again to clear. The active letter pulses on a 1.2-second breathing glow so it's obvious which letter is currently filtering the view; `prefers-reduced-motion` swaps the pulse for a static glow. The filter resets automatically on folder navigation, search, or going back to the library root so it never carries over into an unrelated view.

##### Changed

- **Emby `/Items` query now requests `SortBy=SortName&SortOrder=Ascending`.** Emby strips leading articles for `SortName` -- "The Matrix" sorts under M, "An Inconvenient Truth" under I -- so the A-Z jump bar lands on the letter the user actually reaches for. Doing the sort at the Emby query layer keeps pagination boundaries aligned with the displayed order; a client-side re-sort after fetching would have scrambled page boundaries.

##### Fixed

- **A-Z jump bar letters were dim until the user scrolled.** The library is paginated (50 items per page), so on a fresh mount the bar's dim/active state only reflected page 1's letter range and the rest stayed grey until the IntersectionObserver-driven scroll loader fetched more pages. Pagination was the right perf model for the original "browse and scroll" UX but it broke the new "see which letters have content at a glance" expectation. After the first page returns on a library with `>=30` items (the threshold that shows the bar), a sequential cascade-loader walks the remaining pages in the background so the bar fills out without any scroll input. The scroll-trigger still works in parallel via the existing `loadingMore` gate -- if you scroll past the sentinel before the background loop reaches that page, the sentinel wins, no double-fetch.

#### [2.0.0-beta11] - 2026-06-17 - Reverse-proxy support + multi-version playback

##### Added

- **`APP_PREFIX` reverse-proxy support is wired end-to-end again** (it had been read from `.env` and logged at startup since the rewrite but every URL-bearing surface ignored it -- backend routers were mounted at root, the Socket.IO endpoint hardcoded `/socket.io`, the frontend asset bundle assumed `/assets/...`, the api client called `/api/...` directly, and the socket store connected to `/socket.io`). Setting `APP_PREFIX=/watchparty` in `.env` now puts everything under that subpath the way 1.x did, so a single uvicorn process can sit behind a reverse proxy that forwards `https://example.com/watchparty/...` without rewriting the path. Backend: every router included with `prefix=APP_PREFIX`, Socket.IO mounted at `${APP_PREFIX}/socket.io`, static `/assets` mounted at `${APP_PREFIX}/assets`, and an SPA catch-all + root-redirect that send a `307` from `/` to `${APP_PREFIX}/` so users who forget the prefix land where they expect. Frontend: Vite builds with `base: './'` for relative asset URLs, the backend injects `<base href="${APP_PREFIX}/">` plus `<script>window.APP_PREFIX = "...";</script>` into served `index.html` so Vue Router, api/client, and the socket store all read the prefix at runtime without a rebuild (one image, many deployment paths). The single-image-many-paths approach matches what 1.x did via Flask templates rendering `{{ app_prefix }}`. Address `APP_PREFIX` bug report from Discord.
- **Multi-version playback** with the host-locked version picker in the library ([#43](https://github.com/Oratorian/emby-watchparty/issues/43), [@wlowen](https://github.com/wlowen)). When Emby has more than one MediaSource for an item (theatrical / director's cut, mp4 / mkv, 1080p / 4K HDR, etc.), clicking the library card opens a small modal listing every version with its label, container, and runtime; the host picks one and that version is locked party-wide for the playback. Single-version items skip the modal entirely -- the click-to-play flow is unchanged. Audio / subtitle / quality changes carry the chosen version forward automatically (the backend reads `current_video.media_source_id`, never from the per-change payload), and late joiners + vote-pass restarts land on the same source instead of silently bouncing back to Emby's default. New endpoint contract: `GET /api/item/<id>/streams` returns a `versions` array (`{id, name, container, run_time_ticks}`) alongside `audio`/`subtitles`, and accepts an optional `media_source_id` query so the audio/subtitle lists describe the version that's actually playing.

##### Changed

- **`ToggleSwitch` defaults its model to `false`.** Previously `defineModel<boolean>()` (with no default) yielded `Ref<boolean | undefined>` which forced every `@update:model-value` handler at every call site to accept `boolean | undefined`, surfaced as type errors during `vue-tsc --build` after the granular-quality refactor added `update:model-value` listeners with explicit `(v: boolean)` callbacks. The component now defaults to `false`, so the emit signature is `(value: boolean) => any` and call sites can pin to plain booleans. A toggle should never have an undefined state anyway -- it always represents a definite on/off.

##### Fixed

- **WebSocket upgrades 404'd whenever `APP_PREFIX` was set.** `python-socketio`'s ASGI driver normalises its `socketio_path` parameter to `/<path>/` and matches against `scope['path']` -- and contrary to what most docs imply, Starlette's `Mount` preserves the full URL path in `scope['path']` rather than stripping the mount prefix. So when `APP_PREFIX=/watchparty` mounted the socket app at `/watchparty/socket.io`, engineio saw `scope['path'] = '/watchparty/socket.io/'` but was configured to match `/socket.io/`, dropped the request to its 404 handler, and uvicorn's WebSocket protocol crashed with `Expected ASGI message 'websocket.accept' but got 'http.response.start'`. Fixed by setting `socketio_path` to the full mounted path (`${APP_PREFIX}/socket.io`) so engineio's startswith check matches what Starlette actually delivers.
- **Asset 404s + MIME-type errors on hard refresh of any nested SPA route under `APP_PREFIX`.** Vite's `base: './'` makes built `index.html` reference assets as `./assets/...`, which the browser resolves against the page URL. At `/watchparty/` that gives `/watchparty/assets/...` (correct), but at `/watchparty/party/CODE` it gives `/watchparty/party/assets/...` -- the SPA catch-all then served HTML for the missing JS path, which the browser rejected as a JS module ("not allowed by MIME type 'text/html'"). Backend's SPA handler now injects `<base href="${APP_PREFIX}/">` as the first element in `<head>` so the browser always resolves relative URLs against the SPA root regardless of how deep the current route is.
- **Pre-existing strict-TS errors that blocked `npm run build`** (`vue-tsc --build`, stricter than the `--noEmit` smoke we'd been running during development). `hiddenParties.ts` and `PartyView.vue` matched a regex and dereferenced the capture group without proving it was defined; both now guard explicitly. Caught while preparing this beta -- not user-visible, but `npm run build` is the CI entry point for every Docker image build.

#### [2.0.0-beta10] - 2026-06-16 - Refined Cyber refresh + bitrate-granular quality

The "Refined Cyber" design language is adapted from a mockup by [Christian Gillinger](https://github.com/cgillinger). Design credit in [Special Thanks](#special-thanks).

##### Added

- **Refined Cyber design refresh.** Cyan/magenta/violet palette swap on the global tokens, atmospheric body gradient (cyan + magenta + violet radials), Inter font feature settings + tighter letter-spacing. Global buttons and inputs move to chip/pill language (9px radius, surface bg, cyan focus glow). Topbar gets a glass background with backdrop blur; library and chat panels share the same surface stack so the layout reads as one continuous treatment.
- **Brand-mark logo** in the topbar -- synthwave V-monogram replaces the placeholder play-arrow tile. Sits inside a rounded 64px tile with a soft cyan-tinted shadow, with a clickable brand link that opens the version modal.
- **Header chips.** Party-code pill with copy icon, viewer chip with overlapping avatars + green live dot + `+N` overflow, chip-style Browse Library / Stop Video, Admin gear icon button, red-tinted Leave button. Host badge restyled as an amber pill.
- **LIVE badge with animated equalizer bars** overlays the currently-playing library card, with a cyan-tinted border + faint glow so the active item is obvious when the library opens over the player.
- **System messages** ("X paused playback", "X seeked to ...") render as centred pill bubbles with a cyan check icon, replacing the previous left-bordered italic text.
- **Active parties on the index.** When `REQUIRE_LOGIN` is off, the home page lists every active party with at least one member, polled every 5 seconds, showing the current video title (or "in lobby" when no video has been picked yet) and the member count. Clicking a row joins that party, which triggers the normal late-joiner vote when a video is already playing. If the vote denies you, the party's code is added to a per-browser `parties_hidden` cookie (1-day max-age) and is filtered out of subsequent listings so a rejected user is not repeatedly tempted to re-request it. Backed by `GET /api/party/list` (anonymous, returns `{require_login, parties: [{code, title, user_count, playing, locked}]}`; deliberately empty when `REQUIRE_LOGIN` is on so the set of open parties and what they are watching is not advertised). DEBUG-level logging only, since the endpoint is polled.

##### Changed

- **Quality menu rewritten to mirror Emby's per-resolution table.** The five hardcoded presets (`1080p-high` ... `360p`) are replaced by a single flat dropdown driven by the new `GET /api/quality-options` endpoint. The dropdown shows `Auto` (no caps, lets Emby decide -- stream-copy possible when the source matches HLS) followed by every enabled resolution expanded into its full bitrate range, exactly mirroring Emby's own quality menu: 1080p has 13 entries (4 / 5 / 6 / 8 / 10 / 12 / 15 / 20 / 25 / 30 / 40 / 50 / 60 Mbps), 720p has 5 (1 / 1.5 / 2 / 3 / 4 Mbps), 480p has 3 (420 kbps / 720 kbps / 1 Mbps), and 360p / 240p / 144p are resolution-only. Selecting any explicit bitrate forces a transcode at that cap (`MaxStreamingBitrate`); `Auto` is the only entry that keeps stream-copy on the table for unbounded h264 sources. A new admin setting **`ENABLED_QUALITY_OPTIONS`** (`dict[str, list[int]]` mapping resolution to enabled bitrates, surfaced in a new "Quality" card as a per-resolution toggle plus a collapsed bitrate disclosure that only opens when the resolution is on) lets the admin pick both the resolutions and the bitrates within each one, so deployments can expose, for example, 1080p at only 10 / 8 / 6 Mbps and hide everything below 720p entirely. `Auto` is automatically hidden when `FORCE_TRANSCODE` is on (it would conflict with always-transcode and let h265 sources balloon their bitrate without a cap), and `1080p / 10 Mbps` becomes the default in that mode. Existing party state with legacy preset strings (`1080p-high` etc.) maps to the nearest current id on read, so no migration step is required. Addresses [#41](https://github.com/Oratorian/emby-watchparty/issues/41).
- **Skip buttons in the controls strip.** A new `Jump` button group (`-30s` / `-10s` / `+10s` / `+30s`) sits next to the existing Audio / Subtitles / Quality / Skip Intro controls. Each click computes `currentTime + delta` (clamped to `[0, run_time_seconds]`) and routes through the same socket `seek` path Skip Intro uses, so the server broadcast drives the actual seek for everyone in the party rather than the clicker seeking ahead locally.

##### Fixed

- **Subtitles disappeared on every quality switch and could not be toggled back on.** Emby returns the same `media_source_id` across transcode sessions for the same item, so a quality change only changed the per-user stream URL, not the media-source key the subtitle-preload watcher was keyed on. The watcher early-outed, HLS reattach reset every `textTrack.mode` to `'disabled'`, which unloaded the cues, and the existing Chromium-bug workaround for `'disabled' -> 'showing'` no-op meant toggling None and back from the dropdown never reloaded them either. The watcher now keys on `(item_id, media_source_id, myStreamUrl)`, the user's selected text-sub index is tracked in Vue state (so it survives the HLS-driven mode reset) and re-applied after the next `loadeddata`, and the preload rebuilds the `<track>` set on every stream change so the cues are fetched fresh.

#### [2.0.0-beta9] - 2026-05-24 - Vote resolve + Docker fixes

##### Fixed

- **Late-joiner vote never resolved and the modal hung forever** (reported by StealthyDruid). When a vote fell through to the timeout instead of resolving on an immediate majority, the timeout watchdog cancelled its own asyncio task before emitting the result, so `join_vote_resolved` never reached the clients. Separately, the selector tiebreak looked up a client_id in the sid-keyed votes map and so could never find the selector's vote. The watchdog no longer cancels itself, and the selector's vote is resolved via its current sid, so the vote always concludes (immediately on a vote, or via the timer).
- **Video player clipped the top of the frame with no way to scroll back** (reported by StealthyDruid). The player height was pinned to `calc(100vh - 180px)`, a hardcoded guess for the surrounding chrome (header, controls, info). When the real chrome was taller, for example a wrapped header on narrow or side-by-side windows, the video overflowed its slot and the top was clipped unreachably; only fullscreen recovered it. The player now sizes to its actual flex space (`min-height: 0` down the chain plus `object-fit: contain`), so it always fits regardless of chrome height.
- **`WATCH_PARTY_PORT` and `WATCH_PARTY_BIND` were ignored in Docker.** The image hardcoded `uvicorn ... --port 5000`, so the documented env vars had no effect on the container. The app now has a real entrypoint (`python -m backend.app`) that binds `WATCH_PARTY_BIND:WATCH_PARTY_PORT`, honoured by both Docker and bare-metal runs.
- **Docker healthcheck queried `/api/version`** (which performs an external GitHub update check) instead of the dependency-free `/api/health`, risking false-failure restart loops when GitHub was slow or unreachable. Switched to `/api/health`, and the healthcheck now follows the configured `WATCH_PARTY_PORT`.
- **Docker build failed when `node_modules` was present in the build context** (for example synced from a Windows share without the executable bit), which clobbered the fresh `npm ci` and broke `vite` with exit 126. `node_modules` is now excluded via `.dockerignore`.
- **Late-joiner vote passed but the video never restarted.** `_resolve_vote_pass` called `restart_video_from_beginning` with `selector_sid=`, but the parameter is `selector_client_id`, raising a `TypeError` that aborted the restart after the resolution event had already fired. Corrected the keyword so a passed vote actually restarts the video and admits the joiner. *(Post-beta9 hotfix included in this section.)*
- **Vote modal stayed open after a passing vote.** PartyView's listener-dedup `socket.off()` list included `join_vote_resolved`, which stripped the party store's handler that clears `pendingVote` (PartyView's own handler only redirects rejected joiners and relies on the store's). Dropped it from the off-list, mirroring the existing `sync_state` carve-out, so the modal dismisses on resolution. *(Post-beta9 hotfix included in this section.)*
- **`LOG_LEVEL` / `CONSOLE_LOG_LEVEL` changes from the admin panel had no effect until a restart.** The logger was built once at startup and never reconfigured. Levels are now re-applied live, with the logger held at the most verbose of the two so a more-verbose console handler actually receives records (e.g. `CONSOLE_LOG_LEVEL=DEBUG` surfaces debug on stdout without flooding the log file). Applied identically at boot and on admin-panel changes. *(Post-beta9 hotfix included in this section.)*
- **Library did not lock when the host left the party explicitly.** Host-leave handling lived only in the socket `disconnect` path; clicking "Leave Party" fires `leave_party`, which keeps the socket connected and erases the host's sid mapping before the disconnect handler could use it, so remaining users kept an unlocked library. `leave_party` now detects the departing host and transitions the lock immediately (PLAYING-ONLY while a video is active so others' streams finish, otherwise LOCKED), emitting `host_left`. *(Post-beta9 hotfix included in this section.)*

#### [2.0.0-beta8] - 2026-05-22 - Skip Intro, subtitles, FORCE_TRANSCODE, bundle slim

##### Added

- **`FORCE_TRANSCODE`** admin-panel toggle under a new "Playback" section (default off). When on, every HLS URL carries `EnableAutoStreamCopy=false` so Emby always re-encodes, producing uniform 6-second segments that HLS.js can seek into cleanly. When off (default), Emby decides per source and h264 content within the bitrate cap is stream-copied for lower CPU/GPU load. Turn this on if large seeks (Skip Intro, dragging the progress bar) restart playback from the beginning.

##### Fixed

- **Skip Intro restarted playback from the beginning.** Three independent bugs: `/api/intro` returned 403 because it was signing the request with the spectator's access token instead of the admin server key; `onSkipIntro` issued a redundant local `currentTime = ...` assignment that fought the server-driven seek; and stream-copied sources have wide keyframe spacing that breaks large HLS seeks. Backend now uses `EMBY_API_KEY`, the local seek was dropped, and stream-copy can be force-disabled via the new admin toggle.
- **Phantom-seek guard rejected real progress-bar seeks.** The delta-based guard compared the new position to `lastNaturalTime`, but `timeupdate` fired before `seeking` and clobbered that reference with the seek target, so the diff was always zero. Replaced with an `isUserSeeking` flag that the VideoPlayer toggles on the genuine user-initiated seek path.
- **Subtitle default was selected in the dropdown but not displayed.** Setting `track.mode = ...` cast through `(track as any)` was a no-op on the Vue-wrapped `HTMLTrackElement`. Now sets `track.track.mode` after the element is appended.
- **Choosing "None" left subtitles permanently disabled.** The "None" branch unconditionally emitted `change_streams`, which rebuilt the HLS stream and unloaded the side-channel `<track>` cues. Switched the None branch to `mode = 'hidden'` and added a `wasBurnedSub` latch so `change_streams` only fires when transitioning to/from a burned-in PGS sub.
- **Sub change paused the whole party.** The native `pause` event fired by HLS during a `change_streams`-driven `src` swap was being broadcast as a party-wide pause. Now suppressed by checking `myStreamReloading` in the play/pause emitters.
- **Late joiner saw "Party is locked" on first refresh.** `auth.refresh()` ran before the new session cookie was bound, so the joiner appeared to have no party. Now calls `auth.refresh()` immediately after `api.joinParty()` resolves.
- **Username modal flashed on every rejoin** while auto-join was still resolving. Added an `awaitingAutoJoin` guard that suppresses the modal until the auto-join attempt completes or fails.
- **`navigator.clipboard` was undefined on LAN deployments** because non-HTTPS contexts don't expose it. Added a hidden-textarea + `execCommand('copy')` fallback in a new `utils/clipboard.ts` helper. Avatar copy button now also flips its label to "Copied!" for 1.5 s to match the party-code button.
- **Admin button missing for an Emby-admin host.** AdminView is now linked from the party header behind `v-if="auth.isAdmin"`. Logging in via `/admin` and then creating a party also keeps the admin Emby token stashed in the session, so the user is auto-promoted to host on create instead of being asked for credentials again.
- **"Back to WatchParty" from `/admin` or `/version` always pointed to `/`.** Both views now compute the back target from `auth.partyId` so an admin returning from settings lands back in their active party with the session intact.
- **`party.leave()` left the session cookie in place.** New `POST /api/party/leave` endpoint clears `party_id`, `client_id`, `display_name`, and `avatar_uuid` from the session before the store resets local state.

##### Performance

- **Initial bundle slimmed via async-loaded components.** `LibraryBrowser`, `EmojiPicker`, modals (`JoinVoteModal`, `JoinWaitingRoom`, `EmbyLoginModal`, `AvatarSetupModal`), and IndexView's `EmbyLoginModal` are now loaded on demand via `defineAsyncComponent`. `hls.js` is split into its own rollup chunk so it loads only when a stream actually starts. PartyView dropped from ~569 kB to ~36 kB; the home/join flow no longer pays for HLS until playback begins.

#### [2.0.0-beta7] - 2026-05-15 - Late-join + change-streams stability pass

##### Added

- **OpenAPI annotations on every binary-response endpoint** (`/api/avatar/{uuid}`, `/api/avatar/host/{party_id}`, `/api/image/{item_id}`, `/api/subtitles/...`, `/hls/{item_id}/master.m3u8`, `/hls/{item_id}/{subpath}`). `/docs` and `/redoc` now show the right content-type tables (image/*, text/vtt, application/vnd.apple.mpegurl, video/MP2T) and document the failure status codes.

##### Fixed

- **`GET /api/party/<id>/info` and `GET /api/item/<id>` returned 500** when the target was missing: their error-fallback `{"error": ...}` dict didn't satisfy the route's `response_model`, so FastAPI's response validation raised a `ResponseValidationError`. Both now properly return `404` with a `detail` field.
- **`GET /api/item/<id>/streams` silently swallowed upstream failures** inside a 200 response. The error key was stripped by Pydantic v2's default `extra="ignore"`, so the caller saw empty stream arrays and no signal that anything went wrong. Now returns `502` honestly when stream metadata cannot be fetched.
- **`GET /api/party/<id>/exists` had no `response_model`** so its OpenAPI entry was untyped. Added `PartyExistsResponse`.

#### [2.0.0-beta6] - 2026-05-14 - Host-provider auth model + chat avatars

##### Added

- **Host-provider auth model** (resolves [#31](https://github.com/Oratorian/emby-watchparty/issues/31)). Each party has a host -- the Emby-authenticated member whose `access_token` signs every Emby call for that party. Three-state lock: UNLOCKED (host present), PLAYING-ONLY (host left mid-playback, current video keeps streaming until natural end), LOCKED (no host, library inaccessible). A 5-second grace window around the host's socket disconnect treats a quick refresh as a reclaim, not a departure; longer absences trigger a `host_left` broadcast and the state transition.
- **Custom chat avatars** (resolves [#36](https://github.com/Oratorian/emby-watchparty/issues/36)). Each user can upload an image, link a Gravatar by email, or restore a previously-set avatar with a memorable three-word recovery code. Hosts who logged in with Emby and have not set their own avatar fall through to their Emby profile picture. Spectators without any avatar still get the deterministic monsterid fallback. Identity is owned by an opaque UUID stored in IndexedDB / localStorage and never tied to chat usernames, so changing your display name does not change your avatar. Recovery codes are bcrypt-hashed at rest; `/api/avatar/recover` is rate-limited to 10 attempts/hour per IP. New endpoints: `POST /api/avatar/upload`, `POST /api/avatar/gravatar`, `POST /api/avatar/recover`, `GET /api/avatar/{uuid}`, `GET /api/avatar/host/{party_id}`. New Docker mount points: `/app/data` (SQLite store), `/app/images/avatars` (uploaded files).
- **`POST /api/party/<id>/join`**: issues the party-bound session cookie used by every protected route and the Socket.IO handshake. Anonymous (no Emby credentials).
- **`POST /api/auth/logout`**: drops host status without leaving the party. Emits `host_left` to the room.
- **`GET /api/auth/status`** returns the caller's relationship to their current party (`{ authenticated, is_host, is_admin, host_username, party_id, party_unlocked, require_login }`).
- **`EmbyLoginModal` Vue component** reused by both the create-party flow (when `REQUIRE_LOGIN=true`) and the in-party "Login to Become Host" flow.
- **`GET /api/health`**: anonymous liveness endpoint for Docker / Kubernetes / reverse-proxy healthchecks. Returns `{status, version, codename}` and intentionally does not contact Emby or the avatar DB, so a transient upstream blip cannot flap container restarts.

##### Changed

- **Admin panel auth**: now Emby-admin-only when login is required, verified via `IsAdministrator` policy from the auth response.
- **`EmbyClient` is now stateless per identity.** Constructor no longer takes `username` / `password`; every user-scoped method (`get_libraries`, `get_items`, `get_playback_info`, `report_playback_*`, etc.) accepts an explicit `access_token` and `user_id`. The host's token signs each call. Closes the long-standing service-account leak where `.env`-stored credentials signed every Emby request regardless of who initiated it.
- **Selector identity is keyed on `client_id`**, not socket sid. Refreshing the page no longer transfers the Stop-Video right or party-clock authority to whoever's sid happens to take over.

##### Fixed

- **`/admin` navigation unbound the party.** PartyView's `onUnmounted` was calling `party.leave()`, which dropped the session cookie. Removed; explicit leave still works via the Leave button.

#### [2.0.0-beta5] - 2026-05-10 - Library navigation, UX polish, subtitle finalisation

##### Added

- **Library browse position persists across refresh / rejoin / app restart**: drilling into Movies > Action then reloading the page now lands you back in Action with the breadcrumb intact. Saved per-browser in localStorage, falls back to the root if the saved item no longer exists.
- **Library auto-opens on Stop Video**: clicking Stop Video pops the library open in one gesture instead of leaving everyone on a "Browse Library" button. Fires for every user in the party.

##### Fixed

- **HLS transcode silently picked stream-copy** over real transcoding for some sources, breaking quality presets. `EnableAutoStreamCopy=false` ported from 1.6.3.
- **Phantom "Andrew seeked to..." chat spam during normal playback** at 5-6 messages per second. Looked like real seeks; was actually Vite HMR stacking duplicate socket listeners across reloads. Fixed by clearing existing listeners before re-registering at every setup point.
- **Subtitle architecture conflict** between HLS.js manifest text tracks and side-channel `<track>` elements (1.6.6 backend + frontend backport). Manifest text-sub params removed from the HLS URL; side-channel proxy is now the single source for text subs. CC menu shows distinct labels for variants like `English (Signs & Songs)`, `English [Forced]`, `English [External]`.
- **CC menu duplicate "Subtitles" entry** when the dropdown's initial-default emit raced the auto-load. Auto-show for the default text sub now happens inside the auto-load watcher so there is no parallel emit to race with.
- **Static session settings required a full restart** to take effect. Toggling "static session = X" via /admin now applies immediately; renaming the id without restart also works.
- **Emoji picker right-side cropping** caused by `.party-content`'s `overflow: hidden` clipping the absolutely-positioned panel. Picker now teleports to `<body>` with computed `position: fixed`, escaping the clip context entirely.
- **Emoji picker scroll jitter** where scrolling the picker shifted it leftward by sub-pixels per wheel tick. Capture-phase scroll listener was firing on the picker's own internal scroll; switched to default-phase so only page-level scroll triggers reposition.
- **Folder-organised libraries appeared empty** ([#34](https://github.com/Oratorian/emby-watchparty/issues/34)): browsing a Movies library laid out as `Movies/Blade/Blade.mkv` (one folder per title) returned an empty card grid, while flat-file libraries like `Movies/Blade.mkv` worked. Backend now derives `IncludeItemTypes` and `Recursive` from each library's `CollectionType`, so Emby resolves folder shadows to the underlying movies / series regardless of on-disk layout.
- **Library card posters were cropped** ([#35](https://github.com/Oratorian/emby-watchparty/issues/35)): cards used a hardcoded 2:3 aspect ratio that distorted square collection icons and wide channel banners. Each card now reads its `PrimaryImageAspectRatio` from Emby and styles itself accordingly.
- **Browser tab title was the Vite default** ([#33](https://github.com/Oratorian/emby-watchparty/issues/33)): updated to "Emby Watch Party - Tonight's Premiere".
- **"Enter Party Code" placeholder was clipped** ([#37](https://github.com/Oratorian/emby-watchparty/issues/37)): the input's uppercase + 0.15em letter-spacing made the placeholder wider than the input, so Chrome chopped the last few characters. Shortened to "Party code" and added `::placeholder` rules that disable the uppercase/letter-spacing styling for placeholder text only.
- **Phantom "seeked to..." chat spam during normal playback** in production builds (separate from the HMR-driven version in dev): the `socket.on('seek')` broadcast handler unconditionally assigned `ve.currentTime = streamTime` even when the deltas matched, which queued a fresh `seeked` event that fired after `isSyncing` had already reset, escaping the guard and being rebroadcast to the party. The assignment is now gated behind a 0.3s delta check, and `onVideoSeeked` tracks natural playback progression so spurious browser-fired `seeked` events on startup don't get rebroadcast either.

#### [2.0.0-beta1] - 2026-05-08 - Initial closed beta (foundation)

Beta1 was the first build cut from `2.0-Rework` for closed testing. Beta2 through beta4 followed in the next 48 hours as rapid iterations with no separate release notes; their content is rolled into this section.

##### Added

- **Per-user transcodes**: each user gets their own Emby transcode session and HLS stream, so audio language, subtitle selection, and quality can be different per user without disrupting the rest of the party.
- **Late-joiner vote flow**: when someone tries to join mid-playback, existing users vote on whether to admit them. If the vote passes, the video restarts from the beginning so everyone lands on the same PTS-aligned segment. Vote modal for existing users, waiting-room screen for the joiner. Selector tiebreak on timeout, default-no fallback, 30s cooldown after a failed vote to prevent URL-spam griefing.
- **Silent `change_streams`**: switching audio, subtitle, or quality mid-playback now swaps only your own stream without pausing the rest of the party.
- **Admin panel** (`/admin`) with hot-reload: 17 runtime settings editable from the UI, no restart needed. Two-tier config splits boot-essential `.env` vars from mutable runtime settings persisted to `config.json`.
- **OpenAPI documentation** at `/docs` and `/redoc`. All JSON endpoints have typed Pydantic response schemas so the spec is complete.
- **User docs** in the [project wiki](https://github.com/Oratorian/emby-watchparty/wiki) covering the full end-user experience including the vote flow, admin panel, and troubleshooting.
- **Mobile chat panel**: chat slides in over the video on narrow screens with a tap-to-dismiss backdrop. (NewBlade)
- **Reload-as-rejoin**: refreshing the page in an active party is now recognised as a rejoin instead of triggering a vote on yourself. (NewBlade)
- **Codename system**: 2.0 carries the codename "Midnight Premiere", shown on the version page and in the startup banner.

##### Changed

- **Full rewrite to FastAPI + Vue 3 + TypeScript**. python-socketio AsyncServer replaces Flask-SocketIO. Vue Router with 6 routes (Index, Party, Login, Admin, Version, 404). Pinia stores for auth/party/socket state. Vite for dev + build. uvicorn replaces gevent as the ASGI server. httpx for async HLS proxying. socket.io-client for real-time sync.
- **Foundation refactor (5 phases)** before the rewrite: introduced `PartyManager`, app-factory pattern with compatibility shims, eliminated string-bool comparisons, merged `run_production.py` into `app.py` as a single entrypoint.
- **Per-user subtitle delivery**: text subtitles via side-channel proxy (`/api/subtitles/...`), image subtitles burned in via per-user transcode. Unified subtitle dropdown shows both with `text` / `burned in` markers in the label. (NewBlade)
- **Selector-only sync authority**: only the user who selected the video can issue play/pause/seek. Non-selector events are silently dropped to prevent state corruption.

##### Fixed

- **Page reload triggered a late-joiner vote** on the user who refreshed. Now recognised as a rejoin via persistent `client_id`. (NewBlade)
- **Default subtitle from Emby** was selected in the dropdown but never actually displayed. Fixed. (NewBlade)
- **Subtitle dropdown hid all text-based subtitles**, leaving only burned-in image subs available. Fixed. (NewBlade)
- **Text subtitle track activation** raced with the `<track>` element's `load` event. Fixed. (NewBlade)
- **Drift correction immediately flagged everyone as several seconds behind** the moment a ready check resolved. Fixed. (NewBlade)
- **Browser pause events fired during seeks** were broadcast to the rest of the party, causing flicker. Now debounced. (NewBlade)
- **Seek events left the server's playing state stale**, causing intermittent state divergence between clients. Fixed. (NewBlade)

##### Removed

- **Old Flask frontend** (`src/`, `static/`, `templates/`, `app.py`). The Vue 3 build at `frontend/` produces static assets served from `backend/static/` so a single uvicorn process serves both.
- **Tracked `config.json`** is now generated from `RuntimeConfig` defaults on first run and gitignored, since values are deployment-specific.
- **`EMBY_USERNAME` and `EMBY_PASSWORD` env vars.** See Breaking Changes.
- **Global LoginView** (`/login` route). Replaced by the in-party "Login to Become Host" flow.

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

**CollectionType-aware library queries**

1.x always hit the user-scoped `/emby/Users/{userId}/Items` endpoint and Emby's auto-resolution worked because the legacy code paths set `IncludeItemTypes=Movie` and `Recursive=true` for movies. 2.0's initial port queried the global `/emby/Items` endpoint with neither flag set, which returned `Folder` items for folder-organised layouts -- a movie at `Movies/Blade/Blade.mkv` came back as a `Folder` named "Blade" with no metadata, and the frontend filtered Folders out, leaving an empty grid.

`EmbyClient.get_items` now caches the `CollectionType` of every top-level library at startup (`_ensure_library_cache`), and when a `ParentId`-scoped browse comes in without an explicit `item_type`, derives the right query parameters from the parent library's collection type:

- `movies` library: `IncludeItemTypes=Movie`, `Recursive=true` -- folder-per-movie resolves to the movie inside.
- `tvshows` library: `IncludeItemTypes=Series`, `Recursive=false` -- top level is series, deeper navigation resolves seasons/episodes natively.
- `boxsets`: `IncludeItemTypes=BoxSet`.
- `music`: `IncludeItemTypes=MusicArtist`.
- `homevideos` / `photos`: `IncludeItemTypes=Video,Photo` with `Recursive=true`.

The frontend keeps a defensive fallback: items whose `Type` is in the `displayableTypes` set are kept; if a response contains zero displayable items, Folders are allowed through so a misclassified library is at least navigable rather than empty.

**Per-card aspect ratio for library cards**

Card thumbnails were styled `aspect-ratio: 2 / 3` to match standard movie posters. That distorts every non-poster image Emby returns -- collection icons are typically square, channel banners are 16:9, music album art is square. The `LibraryItem` schema already includes `PrimaryImageAspectRatio` (Emby returns this for every item that has a primary image), so `LibraryBrowser.vue` now computes an inline `aspect-ratio` style per card from that value, falling back to 2:3 only when Emby provides no aspect ratio at all. Tall posters, square album art, square collection icons, and wide channel banners all render at their intended dimensions in the same grid without per-item CSS classes.

**Phantom seek-cascade in per-user transcodes**

Symptom on production builds (not just HMR): chat flooded with "Andrew seeked to 00:01 / 00:02 / 00:03..." during normal playback in a per-user-transcode party. The HMR-stacking fix above eliminated the development reproduction but did not eliminate the production one.

Actual root cause: `socket.on('seek', ({ time }) => { isSyncing.value = true; ve.currentTime = time; ... })`. The assignment was unconditional, so even when the local `currentTime` already matched the broadcast time (within rounding), HTMLMediaElement still fired a fresh `seeked` event a few ticks later. By then the `isSyncing` flag had been cleared in the seek handler's own follow-up, so `onVideoSeeked` saw the spurious event as a real user seek, rebroadcast it via `socket.emit('seek')`, the server fanned it out, every client's `ve.currentTime = time` re-ran, more spurious `seeked` events were queued, and the loop tightened until it was emitting at the engine's tick rate.

Two layered guards:

1. The broadcast handler now only assigns `ve.currentTime` when `Math.abs(ve.currentTime - streamTime) > 0.3`. Matching positions don't trigger the assignment at all, so no spurious `seeked` event is queued.
2. `onVideoSeeked` tracks `lastNaturalTime` / `lastNaturalAt` on every `timeupdate`, and on a `seeked` event compares the new position to the natural projection. If the position lands within ~0.5s of where playback would have advanced to naturally (engine resync on stream warmup, autoplay nudges, network rebuffer adjustments), the seek is treated as natural progression and not rebroadcast.

The 1.x code never had this because it used one shared Emby transcode for the whole party. The party clock and the player clock were defined to be the same thing, so the broadcast handler's "set local time from server time" simply round-tripped to a no-op. In per-user transcodes, each user has their own stream that drifts independently, so the broadcast handler now has actual work to do -- and got too aggressive about doing it.

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

## 1.x line -- migration reference

Only `v1.6.6` (the final 1.x release) is kept below as a reference for users
migrating from 1.x to 2.0, so the last known state of the previous architecture
is visible alongside the 2.0 changelog without having to switch branches. The
full per-version history of every 1.x release (1.0.0 through 1.6.6) lives in
the [git history under the `v1.6.6` tag](https://github.com/Oratorian/emby-watchparty/blob/v1.6.6/CHANGELOG.md).

---

## [1.6.6] - 2026-05-05

### Fixed
- CC button broke when switching between embedded and external subtitles. Fixed.
- HLS subtitle segments returning 401 with token validation enabled. Fixed.

### Changed
- CC menu now shows subtitle variants distinctly. `English (Signs & Songs)`, `English (Full)`, `English (SDH)`, etc.

### Technical details

**CC button broken when switching between embedded and external text subs** ([#29](https://github.com/Oratorian/emby-watchparty/issues/29) follow-up)

1.6.5 enabled HLS manifest subtitles (`SubtitleMethod=Hls` + `ManifestSubtitles=vtt`) so external sidecar SRT/VTT files would appear as native HLS.js-managed text tracks. This created two parallel subtitle delivery paths -- HLS.js's manifest-managed tracks and our existing side-channel `<track>` elements -- which fought over `textTrack.mode` state. Switching from an external (manifest) sub to an embedded (side-channel) sub silently disabled both, leaving "no captions" even though the user clicked a real track. Browser-side diagnostics confirmed HLS.js's state machine was overcorrecting when its manifest track got disengaged. Reverted manifest text-subtitle delivery; the side-channel `<track>` path now owns all text subtitles, eliminating the conflict. PGS / VobSub burn-in still uses `SubtitleMethod=Encode` and is unaffected.

**HLS subtitle segments returned 401** ([#29](https://github.com/Oratorian/emby-watchparty/issues/29) follow-up)

When 1.6.5's manifest subtitle path was active, `subtitles.m3u8` and its VTT segments were proxied without the HLS auth token so token validation rejected them. The token-injection code in the HLS proxy only handled plain URL lines; subtitle playlist URIs live inside `#EXT-X-MEDIA URI="..."` attributes and were silently skipped. Added regex-based token injection for `URI="..."` attributes and broadened the plain-URL injection to handle any non-comment line (covering `.vtt`, `.srt`, `.ass`, and anything else Emby may serve). The fix remains in case the manifest path is reactivated later.

**CC menu subtitle labels**

Subtitle tracks of the same language used to all collapse into identical "English" entries in the CC menu, making it impossible to pick the right one when a file had variants like "Signs & Songs" vs "Full" vs "SDH". The native HTML5 `<track>` label now includes Emby's `Title` field plus `[Forced]` and `[External]` markers so each variant is distinguishable.

---

## Version History Summary

- **v1.6.6** (2026-05-05): CC button switching fix, subtitle 401 fix, label clarity
- **v1.6.5** (2026-05-03): PGS subtitles fixed, Skip Intro 403 fixed
- **v1.6.4** (2026-04-21): Pause/seek after host reconnect fixed
- **v1.6.3** (2026-04-12): `EnableAutoStreamCopy=false` -- the actual seek fix
- **v1.6.2** (2026-04-11): Force-transcode (attempt at seek fix)
- **v1.6.1** (2026-04-10): Peak-bitrate "fix" (later proven a no-op)
- **v1.6.0** (2026-03-22): Drift correction, chat actions, participant list
- **v1.5.x** (2026-03): Quality selector, static session, modular refactor, security fixes
- **v1.4.0** (2026-01-26): APP_PREFIX, playback progress sync, unified entrypoint
- **v1.3.x** (2026-01): `.env`-based config, gevent, library permissions
- **v1.2.x** (2025-11-12): Auto next episode, login gatekeeping, modular architecture
- **v1.1.x** (2025-10): Skip Intro, PGS handling, sync overhaul, themes
- **v1.0.x** (2025-10): Foundation -- core party features, audio fix, HLS proxy

---

## Links

- **Repository**: https://github.com/Oratorian/emby-watchparty
- **Issues**: https://github.com/Oratorian/emby-watchparty/issues
- **Releases**: https://github.com/Oratorian/emby-watchparty/releases

---

## Educational Use Notice

This project is intended for educational purposes and private use only. Please ensure you use this responsibly and in compliance with your Emby server's terms of service and applicable copyright laws.
