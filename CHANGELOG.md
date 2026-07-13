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

## [2.0.1] - 2026-07-14 - Midnight Premiere

A patch release focused on playback control and sync. In 2.0.0 only the host / video selector could play, pause, or seek; everyone else's controls silently did nothing. 2.0.1 makes control **democratic**: any member of the party can play, pause, seek, and skip the intro, and it syncs to the whole room. If one person pauses, everyone pauses -- the way a watch party is meant to work. The library panel also now closes for everyone when a video is picked, and the host's Hide/Show Library button once again follows on every client.

The harder part was doing this without the room dissolving into a pause-storm. The old selector-only gate had quietly been absorbing every client's *synthetic* playback events (buffering pauses, HLS re-alignment seeks, stall-recovery nudges), so opening control to everyone surfaced a class of browser-noise bugs that had been masked for two years. Those guards are now re-established client-side, decoupled from the access model, so shared control and clean sync coexist.

### Changed

- **Playback control is now democratic, not selector-only.** `_authorized_controller` was relaxed from a selector/host gate to a plain party-membership check: any joined member may drive play / pause / seek, and it broadcasts to the whole room. A stray / non-member socket (no registered `client_id`) is still rejected. This deliberately loosens the selector-only gate added during the 2.0.0 security audit -- shared control is the intended watch-party experience for a private, code-gated party. Seek stutter-loops remain guarded by the existing ready-check handshake, independent of who initiates the seek.
- **Library visibility syncs across the party.** Picking a video now closes the library for **every** client (via the symmetric `currentVideo` watcher), not just the picker's own screen. The `toggle_library` client listener dropped in the Vue rewrite is restored, so the host's Hide / Show Library button once again follows on every client -- the server was already broadcasting it to no listener.

### Fixed

- **"Something keeps pausing right after anyone hits play."** The play handler's stall-recovery nudge fires at 1000&nbsp;ms, but the `isSyncing` guard that suppresses synthetic seeks was released at 500&nbsp;ms. So the recovery's `hls.stopLoad()`/`startLoad()` re-seek dispatched a native `seeking` event that the player forwarded as a *user* seek, which the server's "seek during playback" path answered by force-pausing the whole room. A self-inflicted loop on the initiator's own client -- latent since the 2.0 rewrite, but unmasked once democratic control let every client's events reach the room. The stall-recovery re-seek is now wrapped in `isSyncing` so its synthetic events are swallowed. Diagnosed live from DEBUG server logs.
- **Buffering no longer pauses the party.** Under democratic control, a client whose HLS stream stalls fires a native `pause` that would broadcast to everyone. A genuine user pause leaves the element fully buffered (`readyState >= 3`); a stall drops below it. The pause emit is now suppressed while buffering, so one person's connection hiccup can't pause the room.
- **Spectator desync self-corrects.** A resume-only heartbeat safety net re-asserts the authoritative play state when a client's `<video>` drifts from a still-playing party (dropped emit, tab-suspend, OS media key), wrapped in `isSyncing` so it never re-emits or flaps.

Every issue fixed in this release was reported by **[@xyxxyxxy](https://github.com/xyxxyxxy)** -- the play/pause reproduction, the library-not-closing observation, and the "everyone should be able to control the party" call that shaped it. A per-party host-only-vs-everyone toggle is planned for a follow-up.

---

## [2.0.0] - 2026-07-11 - Midnight Premiere

2.0 is a top-to-bottom rewrite of Emby Watch Party. The 1.x line was a Flask app with Jinja templates, vanilla JS on the frontend, and a single shared Emby transcode that the whole party watched in lockstep: one stream URL, one audio track, one subtitle, one quality. It worked, but the architecture made every "can I have my own subtitles", "can I lower my quality on hotel wifi", "why am I stuck on Japanese audio because someone else picked it" request a structural impossibility.

2.0 starts over on three foundations:

- **FastAPI + Vue 3 + TypeScript** replaces Flask + Jinja + vanilla JS. Async end-to-end, typed Pydantic schemas with auto-generated OpenAPI docs at `/docs` and `/redoc`, Pinia stores, Vue Router, Vite for dev + build. A single uvicorn process serves the backend and the compiled frontend from the same Docker image.
- **Per-user transcodes**. Each user gets their own `PlaySessionId` and their own Emby HLS stream. Audio track, subtitle, and quality are now personal settings that can be changed mid-playback without pausing the rest of the party. Drift correction was re-added to keep these independent streams in sync against the authoritative party clock.
- **Late-joiner vote flow**. Per-user transcodes break the old "everyone gets the same Emby segments" guarantee, so late joiners can no longer be slotted in mid-playback without keyframe misalignment. Existing users now vote on whether to admit a late joiner; if the vote passes, the video restarts from the beginning so every session lands on PTS-aligned segment 0.

Around those pillars: an admin panel at `/admin` with 17 hot-reloadable runtime settings, a unified subtitle dropdown that handles text subs (side-channel proxy) and image subs (burned-in transcode) in the same UI, a mobile chat slide-over, reload-as-rejoin via persistent `client_id`, library browse-position persistence, and a codename system. See the **[project wiki](https://github.com/Oratorian/emby-watchparty/wiki)** for the full end-user walk-through.

Codename: **Midnight Premiere**. Branch: `2.0-Rework` (becoming `main` on cutover). Closed-beta images were tagged `2.0.0-betaN` on GHCR through the eighteen-beta cycle; the stable image is tagged `2.0.0` and `:latest`. The three fixes below land on top of `2.0.0-beta18` as the last changes before the stable cut.

### Changed

- **Admin panel opens as an in-party modal.** Clicking the gear icon from inside a party used to route to the standalone `/admin` view, which unmounted the video component and destroyed the HLS.js instance -- returning restarted playback for the whole party. The panel is now extracted into an `AdminPanel` component that mounts as a modal overlay above the player, so opening / saving / closing settings never touches the video. Standalone `/admin` still works for pre-party admins.

### Fixed

- **Silent socket disconnects no longer strand users in the party.** Reported by [@xyxxyxxy](https://github.com/xyxxyxxy) on Discord: a mid-session network blip caused pause / play / seek events to stop reaching the affected user in both directions, with no indication anything had gone wrong -- only a page reload restored sync. Traced end-to-end: the server hard-evicts the user from the party room on `disconnect`, `socket.io-client` auto-reconnects with a fresh sid, and nothing on the client re-issued `join_party`. So the reconnected socket belonged to no party room, and every `sio.emit(..., room=party_id)` silently skipped it. The socket store now tracks a `hasEverConnected` flag; the party store re-emits `join_party` on every subsequent connect (client_id is stable, so the server takes the known-participant fast path via `_replace_sid` -- no late-joiner vote, no lost transcode). An amber "Reconnecting to party…" banner renders during the outage so the drop is visible instead of invisible.
- **Library rescan no longer traps users in a fake-empty grid.** Reported by [@xyxxyxxy](https://github.com/xyxxyxxy) on Discord: mid-scan Emby responses came back empty, the frontend pinned that empty state to `localStorage` as the restore target, and every subsequent mount rendered "no items" until the container was restarted. Three separate bugs stacked: `emby_client.get_items` swallowed `requests.RequestException` into `{}` so a genuine upstream error looked identical to an empty folder; `/api/items` returned no `Cache-Control` header so intermediate proxies could cache the empty page; and `LibraryBrowser.saveLibraryState` unconditionally pinned the current location on load, including when the response was empty. Now `get_items` re-raises and the router returns a proper `502 Bad Gateway`, `/api/items` responses carry `Cache-Control: no-store`, and the localStorage restore target is only pinned when the response actually contained items -- so a mid-rescan empty response is treated as ambiguous instead of authoritative.

The full per-beta breakdown of the 2.0 development cycle (beta1 through beta18, every Added / Changed / Fixed bullet, breaking changes, and technical deep-dives) lives in [SUMMARY-OF-CHANGES.md](SUMMARY-OF-CHANGES.md).



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
- **New `.env` values as of beta18** (session cookie hardening, see beta18 entry below):
  - **`SESSION_SECRET`** — the signing key for the party-bound session cookie. Must persist across process restarts and across every uvicorn worker or existing cookies stop verifying. Previously an anonymous per-process random; now loaded from env. When empty, an ephemeral key is generated with a loud warning at boot — fine for local dev, catastrophic in production. Generate once with `openssl rand -hex 32`.
  - **`SESSION_COOKIE_SECURE`** (default `false`) — when `true`, the session cookie carries the `Secure` flag so it only rides HTTPS requests. Set `true` in every deployment behind TLS. Left `false` in local dev so the cookie still works over `http://localhost`.
  - **`CORS_ALLOWED_ORIGINS`** (default `*`) — comma-separated origin allowlist for the Socket.IO server. The historical `*` remains for backwards compat; production deploys should pin to their actual origin(s) (e.g. `https://watchparty.example.com`) so cross-origin XHR polling from unrelated pages can't open sockets against the server.
- **Session cookie name changed from `session` to `ewp_session` (beta18).** All existing party-bound cookies stop verifying on upgrade; every user is re-prompted to join their party. Sessions issued after the upgrade persist across restarts as long as `SESSION_SECRET` is stable.
- **HLS stream URL no longer carries `api_key=` (beta18).** The URL is now credential-free; the `/hls/...` proxy signs upstream Emby requests via the party's host access token. External tools that grabbed a full HLS URL from a party and expected to hit Emby directly with the embedded key no longer work — the URL only makes sense as a request to the WatchParty proxy from a session-cookie'd browser.

---

## Version History Summary

- **v2.0.1**  (2026-07-14): Democratic playback control (any member can play/pause/seek) + sync-guard fixes.
- **v2.0.0**  (2026-07-11): Official release after 6 months of beta.
- **v1.6.7**  (2026-07-01): Security bump python-socketio to >=5.16.2 (CVE-2026-48804)
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
