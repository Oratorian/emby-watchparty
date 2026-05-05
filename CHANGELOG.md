# Changelog

All notable changes to Emby Watch Party will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Each release has a short user-facing summary on top and a longer **Technical details** section underneath for anyone who wants the full story.

### Special Thanks

Special thanks to **[QuackMasterDan](https://emby.media/community/index.php?/profile/1658172-quackmasterdan/)** for his dedication in testing and providing valuable feedback throughout development.

Thanks to **[wlowen](https://github.com/wlowen)** and **[JeslynMcKenzie](https://github.com/JeslynMcKenzie)** for testing, detailed bug reports, and providing mediainfo that helped track down the HEVC transcoding and HLS seeking issues.

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

## [1.6.5] - 2026-05-03

### Fixed
- PGS / VobSub subtitles weren't displaying since 1.6.3. Fixed.
- Skip Intro button never appeared on items that had intro data. Fixed.

Thanks to **[cimspin](https://github.com/cimspin)** for the precise bug report on [#29](https://github.com/Oratorian/emby-watchparty/issues/29).

### Technical details

**PGS / VobSub subtitles silently broken since 1.6.3** ([#29](https://github.com/Oratorian/emby-watchparty/issues/29))

The HLS URL builder unconditionally added `SubtitleMethod=Hls` + `ManifestSubtitles=vtt` to every request, then separately appended `SubtitleMethod=Encode` when the user picked an image subtitle. The result was a URL with two contradictory `SubtitleMethod` values, so Emby never engaged the burn-in path for image subtitles and they silently failed to display. Restructured `build_stream_params` to compute the subtitle plan once, up front, and emit exactly one consistent set of params per scenario (image-sub burn-in, text-sub manifest, or no selection). Image subtitles are also now filtered out of `SubtitleStreamIndexes`, removing empty placeholder entries from the CC button menu.

**Skip Intro button never appeared (silent 403 on Emby's intros endpoint)**

The `/emby/Items/Intros` admin endpoint was being called with `emby_client.api_key`, which after username/password login holds the user's AccessToken -- user-scoped, and rejected by admin endpoints with HTTP 403 even when the underlying user is admin. The intro route now reads the persistent admin API key from `.env` (`config.EMBY_API_KEY`) directly, bypassing the AccessToken substitution. Symptom was visually indistinguishable from "this item has no intro data" so the bug had been latent since username/password auth was added.

---

## [1.6.4] - 2026-04-21

### Fixed
- Pause and seek silently dropped after a host disconnects and rejoins. Fixed.

Thanks to **[tripleredadam](https://github.com/tripleredadam)** for the detailed bug report and suggested fix approach on [#28](https://github.com/Oratorian/emby-watchparty/issues/28).

### Technical details

**Pause and seek silently dropped after host reconnects** ([#28](https://github.com/Oratorian/emby-watchparty/issues/28))

When the video selector disconnected (network drop, closed tab) and rejoined the party, they received a new socket ID while `current_video.selected_by` still pointed to their dead socket. Pause and seek events were silently ignored because the selector-check compared against the stale sid. The existing eviction path on `join_party` only handled fast page-refresh cases where disconnect hadn't fired yet; a real disconnect-then-reconnect sequence went unhandled. The selector role is now remembered by username as well as sid, so the returning user automatically reclaims control when they rejoin.

---

## [1.6.3] - 2026-04-12

### Fixed
- Seeking was broken on every h264 file under the bitrate cap. Third time's the charm. Fixed for real.

### Added
- HLS request now matches what Emby's own web client sends (faster ffmpeg startup, correct profile/level declarations, native subtitle support).

### Removed
- `EnableDirectPlay=false` and `EnableDirectStream=false` on PlaybackInfo (ineffective, and caused 404s in some configs).

### Technical details

**Seeking broken on all h264 files under the bitrate cap** ([#25](https://github.com/Oratorian/emby-watchparty/issues/25))

v1.6.2's `VideoCodec=h264` only told Emby "I accept h264" and did not prevent stream-copy. The actual fix was `EnableAutoStreamCopy=false` on the HLS request URL, which is Emby's proper API parameter to disable the stream-copy path. Every file now gets a real re-encode with controlled keyframe intervals via ffmpeg (using NVENC/QSV/VAAPI hardware encoding when available). Confirmed via Emby server logs: ffmpeg now uses `-c:v:0 h264_nvenc` instead of `-c:v:0 copy`, and the quality selector actually changes the output bitrate.

**Emby web client parity for PlaybackInfo**

`IsPlayback=true`, `AutoOpenLiveStream=true` (pre-starts ffmpeg so the first HLS segment is ready when requested), `MaxStreamingBitrate`, `AudioStreamIndex`, `SubtitleStreamIndex`, and `StartTimeTicks` are now sent on PlaybackInfo requests, matching what Emby's own web client sends.

**HLS stream parameters**

`MinSegments=1` (reduces initial buffering), `h264-profile` and `h264-level` declarations, `TranscodeReasons` for Emby's transcoding pipeline, and native HLS subtitle support via `SubtitleMethod=Hls` + `ManifestSubtitles=vtt` + `SubtitleStreamIndexes`.

**Removed `EnableDirectPlay=false` / `EnableDirectStream=false` on PlaybackInfo**

These flags only affect Emby's playback method recommendation, not the HLS endpoint's actual transcoding decision. They were ineffective and caused 404 errors in some configurations.

---

## [1.6.2] - 2026-04-11

### Fixed
- Seek failures on VBR h264 files (attempt #2). Fixed... we thought.

### Removed
- The peak-bitrate "fix" from 1.6.1, which turned out to be a no-op.

### Technical details

**Seek failures on VBR h264 files, for real this time** ([#25](https://github.com/Oratorian/emby-watchparty/issues/25))

The actual root cause of the seek/restart bug is Emby's stream-copy HLS path, not peak bitrate. When WatchParty didn't send `VideoCodec=h264` (because the source was already h264 under the cap), Emby remuxed the source's existing bitstream into HLS segments at the source's original keyframe boundaries, while still advertising uniform 3-second segments in the playlist. HLS.js trusted the playlist timing and requested segments that didn't actually contain the expected media, causing 404s, duration jumps, and playback resetting to 0:00. The fix forces `VideoCodec=h264` on every HLS request so Emby always uses the re-encode path with controlled keyframe intervals, producing uniform segments that seek reliably. (Note: this turned out to be insufficient -- see 1.6.3 for the actual fix using `EnableAutoStreamCopy=false`.)

**Removed peak-bitrate check from 1.6.1**

Verified via direct curl tests against Emby's `PlaybackInfo` API that peak/max bitrate is not exposed under any field name. The v1.6.1 "fix" checking `stream.get("MaxBitRate")` was always reading `None` and falling through to average, making it a no-op. Removed to reduce code noise and to be honest about what's actually happening.

---

## [1.6.1] - 2026-04-10

### Fixed
- Seek loop on high-peak-bitrate files (attempt #1).
- Random play/pause/seek event drops.
- NameError in play handler.

### Removed
- Drift correction. Sorry buddy, it failed us again.

### Technical details

**Seek loop on high peak bitrate files** ([#25](https://github.com/Oratorian/emby-watchparty/issues/25))

Quality detection now checks `MaxBitRate` (peak) instead of only `BitRate` (average). VBR h264 files with 3-4 Mbps average but 10+ Mbps peaks were slipping through Direct Play, causing seek failures and playback resets when HLS.js requested segments Emby hadn't generated yet. (Spoiler: this didn't actually work because Emby doesn't expose peak bitrate -- see 1.6.2.)

**Random play/pause/seek event drops** ([#24](https://github.com/Oratorian/emby-watchparty/issues/24))

Removed 0.1s deduplication on incoming sync events. Clients with slightly different `currentTime` were silently dropping legitimate events, causing random failures where some clients would ignore play/pause commands.

**NameError in play handler**

Restored missing `current_video` lookup in `handle_play` that was accidentally dropped during a refactor.

**Removed drift correction** ([#13](https://github.com/Oratorian/emby-watchparty/issues/13))

Backpaddling to not break things. The heartbeat-based system was amplifying seek failures into infinite loops on problematic media files. Will revisit with per-user streams in 2.0.

---

## [1.6.0] - 2026-03-22

### Added
- Continuous sync / drift correction (heartbeat-based).
- Play / pause / seek actions show in chat with username.
- Collapsible participant list in the chat sidebar.
- System message warns users when the browser blocks autoplay.

### Fixed
- Seek resume bug.

### Technical details

**Continuous sync / drift correction** ([#13](https://github.com/Oratorian/emby-watchparty/issues/13))

Heartbeat-based system that detects and corrects playback drift. Only corrects the drifted client without disrupting others. Requires 3+ seconds of drift over 2 consecutive heartbeats to avoid false positives.

**Playback action chat messages** ([#22](https://github.com/Oratorian/emby-watchparty/issues/22))

Play, pause, and seek actions now show in chat with the username of who performed them.

**Participant list** ([#23](https://github.com/Oratorian/emby-watchparty/issues/23))

Collapsible participant list in the chat sidebar showing who is currently in the party.

**Seek resume bug**

Seek events now send the client-side playing state instead of relying on server state, which was stale due to browser pause event ordering during seeks.

---

## [1.5.2] - 2026-03-05

### Fixed
- SocketIO crash on connect with Flask 3.1+.

### Changed
- Bumped flask-socketio dependency.

### Technical details

`flask-socketio` 5.3.5 set `RequestContext.session` which became a read-only property in Flask 3.1; bumped to >=5.4.0 to fix the crash.

---

## [1.5.1] - 2026-03-02

### Fixed
- Several security issues flagged by GitHub code scanning (regex injection, reflected XSS, DOM XSS).

### Changed
- Bumped Flask, python-socketio, and requests dependencies.

### Technical details

**Regex injection in HLS proxy**

Route parameter `item_id` is now escaped with `re.escape()` before interpolation into regex patterns.

**Reflected XSS in image/subtitle proxy**

Proxy responses now use explicit `flask.Response` objects with whitelisted Content-Type and `X-Content-Type-Options: nosniff` headers.

**DOM XSS in party code input**

Party code is now sanitized to alphanumeric characters and URL-encoded before navigation.

**Dependency updates**

Flask 3.0.0 to >=3.1.3, python-socketio 5.10.0 to 5.14.0, requests 2.31.0 to >=2.32.4.

---

## [1.5.0] - 2026-03-02

### Added
- Quality selector (1080p 10/8 Mbps, 720p, 480p, 360p). Feature request by **[wlowen](https://github.com/wlowen)** in [#14](https://github.com/Oratorian/emby-watchparty/issues/14).
- Static session mode (single persistent party that auto-creates on startup). Feature request by **[daniilkopylov](https://github.com/daniilkopylov)** in [#10](https://github.com/Oratorian/emby-watchparty/issues/10).
- UI collapse toggles for header, chat, and video info. Feature request by **[JeslynMcKenzie](https://github.com/JeslynMcKenzie)**.
- Server-side library pagination with infinite scroll. Feature request in [#15](https://github.com/Oratorian/emby-watchparty/issues/15).
- Persistent usernames via localStorage.
- Device profile registration with Emby on startup.
- Version info page and modal.
- Codename system per release.

### Fixed
- Buffering / stutter with HEVC content. Reported by **[wlowen](https://github.com/wlowen)** and **[JeslynMcKenzie](https://github.com/JeslynMcKenzie)**.
- High-bitrate h264 sources causing buffering.
- Video desync on mid-session selection. Reported by **[JeslynMcKenzie](https://github.com/JeslynMcKenzie)**.
- Playback state not resetting when switching videos. Reported by **[JeslynMcKenzie](https://github.com/JeslynMcKenzie)**.
- TV Shows button not displaying results.
- User count incrementing on page refresh. Reported by **[daniilkopylov](https://github.com/daniilkopylov)**.
- Create-party button stuck after browser back ([#18](https://github.com/Oratorian/emby-watchparty/issues/18) by **[JeslynMcKenzie](https://github.com/JeslynMcKenzie)**).
- Log rotation for socketio.log and access.log.

### Changed
- Major modular refactor: split `party.js`, `routes.py`, and `socket_handlers.py` into per-module packages.
- Stream capped to 1080p max. Reported by **[wlowen](https://github.com/wlowen)**.
- Improved log levels.
- Documentation updated.

### Removed
- Dead periodic-sync code from v1.2.

### Technical details

**Quality selection**

Users can choose stream quality from a dropdown (1080p 10Mbps, 1080p 8Mbps, 720p 4Mbps, 480p 1.5Mbps, 360p 0.5Mbps). Quality is party-wide (shared transcode session), persists across media changes and audio/subtitle switches, and late-joining users sync to the current party quality.

**Static session mode**

Single persistent party that auto-creates on startup with a fixed ID. New `STATIC_SESSION_ENABLED` and `STATIC_SESSION_ID` env vars. Users navigating to `/` are redirected straight into the party (no create/join page). Party persists when all users disconnect and is recreated if somehow deleted. Useful for home servers with a small group of regulars.

**UI collapse toggles**

Collapse header, chat, and video info to maximise video real estate. Header collapses to a thin strip with a restore button. Chat collapses to a narrow sidebar button, click to expand. Video metadata/controls footer can be toggled independently.

**Server-side library pagination**

Library browsing now fetches items in pages instead of all at once. Prevents hammering the Emby API with thousands of simultaneous image requests. Infinite scroll with sentinel-based loading for seamless browsing. `IntersectionObserver` for image lazy loading within scrollable containers.

**Buffering/stutter with HEVC content**

Non-h264 sources (HEVC, etc.) now transcode to h264 with a 10 Mbps bitrate cap; h264 sources are direct-streamed/remuxed.

**High-bitrate h264 sources causing buffering**

h264 Blu-ray remuxes (e.g. 24 Mbps) now capped at preset bitrate instead of direct-streamed at full bitrate. Related to [#14](https://github.com/Oratorian/emby-watchparty/issues/14).

**Video desync on mid-session selection**

Selecting a new video while a session was active caused all clients to start at the previous video's playback position instead of 0:00.

**Playback state reset on video switch**

Old video's playback session is now properly stopped before starting a new stream.

**TV Shows button not displaying results**

Client-side display filter only allowed Movie, Episode, and Video types through, silently dropping Series items.

**User count incrementing on page refresh**

Server now evicts stale sessions when the same username rejoins, transferring video control to the new session.

**Create party button stuck after browser back** ([#18](https://github.com/Oratorian/emby-watchparty/issues/18))

`pageshow` event listener re-enables the button when restored from bfcache.

**Modular refactor**

`party.js` (~1965 lines) split into state, chat, sync, library, video, ui, and a slim `party.js` orchestrator. `routes.py` (~1150 lines) refactored into `src/routes/` with 6 focused modules (pages, auth, library, media, hls, party_api). `socket_handlers.py` (~940 lines) refactored into `src/socket_handlers/` with 7 focused modules (connection, party, playback, sync, chat, quality, updates).

**Stream cap**

HLS transcode enforces `MaxWidth=1920` and `MaxHeight=1080`.

**Log levels**

Codec detection, transcoding decisions, and token assignment at INFO; silent error paths at WARNING; AUTH CHECK demoted to DEBUG.

---

## [1.4.0] - 2026-01-26

### Added
- `APP_PREFIX` support for reverse-proxy deployments at a URL path prefix.
- Playback progress sync with Emby server (resume from where you left off).
- Pre-release support in GitHub Actions release workflow.

### Changed
- Unified production entrypoint: `run_production.py` for both Linux and Windows.

### Fixed
- Session cookie for reverse-proxy deployments.

### Technical details

**APP_PREFIX support for reverse proxy deployments**

Deploy at a URL path prefix (e.g., `/watchparty`). New `APP_PREFIX` config option for path-based reverse proxy setups. Uses Flask Blueprint with dynamic url_prefix for native route handling. Socket.IO path automatically configured for prefixed deployments. All templates and API calls updated to respect prefix.

**Playback progress sync with Emby server**

Watch progress now syncs back to Emby. Reports playback start, progress, and stop events to Emby. Periodic progress reporting every 10 seconds. Resume watching from where you left off on any Emby client.

**Pre-release support in GitHub Actions**

Release workflow now handles alpha/beta/rc versions. Auto-detects pre-release tags and sets GitHub release flag accordingly. Skips `latest` and `major.minor` Docker tags for pre-releases.

**Unified production entrypoint**

Consolidated `run_linux_production.py` and `run_windows_production.py` into single `run_production.py`. Both platforms now use gevent, eliminating the need for separate files. Simpler deployment with a single command: `python run_production.py`.

**Session cookie for reverse proxy deployments**

Login now works correctly when using `APP_PREFIX` behind a reverse proxy. Added `SESSION_COOKIE_PATH` configuration to match `APP_PREFIX`. Added `SESSION_COOKIE_SAMESITE='Lax'` for proper redirect handling after login. Fixes issue where session cookie wasn't sent with prefixed routes.

---

## [1.3.1] - 2026-01-24

### Fixed
- Library now correctly filtered by user permissions. Suggestion by **[Spexor](https://emby.media/community/index.php?/profile/1352631-spexor/)**.

### Technical details

Uses `/emby/Users/{user_id}/Views` endpoint instead of `/emby/Library/MediaFolders`. Restricted users only see libraries they have permission to access. Prevents "No items found" errors when clicking inaccessible libraries.

---

## [1.3.0] - 2026-01-23

### Changed
- Configuration migrated from `config.py` to `.env` file.
- Production server switched from Werkzeug to gevent.
- Rate limiting accepts numeric values only.

### Added
- `LOG_TO_FILE` option for Docker stdout-only logging.
- GitHub Actions Docker build to ghcr.io on release.
- Version-check at startup.

### Fixed
- GitHub version check actually runs at startup.
- Rate limiter configuration error with numeric-only values.

### Breaking changes
- Configuration moved from `config.py` to `.env` file -- must migrate settings.
- Application must be run via `run_production.py` (unified entrypoint).
- Removed eventlet dependency (deprecated), now uses gevent everywhere.

### Technical details

**Configuration migrated to .env file**

All settings now loaded from `.env` file using python-dotenv. Copy `.env.example` to `.env` and configure your settings. Old `config.py` values no longer used directly.

**Production server support**

Switched from Werkzeug to gevent for production deployments. `run_linux_production.py` for Linux/Docker, `run_windows_production.py` for Windows. `app.py` no longer runs directly -- use platform-specific entry points.

**Rate limiting simplified**

Now accepts numeric values only (e.g., `RATE_LIMIT_API_CALLS=1000`). Time units added automatically (per minute for API calls, per hour for party creation).

---

## [1.2.1] - 2025-12-18

### Added
- Optional login gatekeeping for public deployments. Feature idea and contribution by **[MaaHeebTrackbee](https://github.com/MaaHeebTrackbee)**.

### Changed
- Boolean configs now store string values for better Docker visibility.

### Technical details

**Optional Login Gatekeeping**

`REQUIRE_LOGIN` config option (default: `false` for backward compatibility). Session-based authentication with configurable expiry (default: 24 hours). Login/logout endpoints with Emby credential validation. Clean login UI matching existing theme system. Automatic redirect handling when login is disabled. Authentication is app-level gatekeeping, not per-user permissions -- all parties still use configured `EMBY_USERNAME`/`EMBY_PASSWORD` for playback. Users authenticate with their own Emby credentials for access control. Login can be completely disabled (default) for private deployments.

**Authentication system (src/routes.py)**

`@login_required` decorator protects routes when `REQUIRE_LOGIN == 'true'`. `/login` route with automatic redirect when login disabled. `/api/auth/login` POST endpoint validates credentials via Emby API. `/api/auth/logout` POST endpoint clears session. `/api/auth/status` GET endpoint returns authentication state. Session management with Flask permanent sessions.

**Templates and configuration**

`templates/login.html` (new login page with theme support). `templates/index.html` (added conditional logout button). `config.py.example` got `REQUIRE_LOGIN` and `SESSION_EXPIRY` options. `docker-compose.yml.example` got login environment variables and a clarification comment. `app.py` got session lifetime configuration.

**Docker improvements**

`Dockerfile` automatically creates `config.py` from `config.py.example` during build. Simplified Docker deployment by automating config file setup.

**Boolean config refactoring**

`REQUIRE_LOGIN`, `ENABLE_HLS_TOKEN_VALIDATION`, `ENABLE_RATE_LIMITING` now store `'true'` / `'false'` strings. Boolean comparisons happen in code (`== 'true'`) instead of config files. Improves Docker environment variable visibility and debugging. Updated all checks in `routes.py`, `socket_handlers.py`, `utils.py`, and `app.py`.

---

## [1.2.0] - 2025-11-05

### Added
- Auto Next Episode feature (binge-watching with countdown overlay).

### Changed
- Episode API now returns IndexNumber, ParentIndexNumber, SeriesId, SeasonId.
- Major modular refactor: split monolithic `app.py` (1913 lines) into `src/` packages.
- Switched to rsyslog-logger for production-grade logging.

### Technical details

**Auto Next Episode feature**

Toggle button to enable/disable auto-next (labeled "Auto Next Episode: ON/OFF"). 4-second countdown overlay when episode ends showing next episode name. Cancel button to stop autoplay during countdown. Automatically plays next episode in season when countdown expires. Tracks current episode position within season. Shows library when reaching end of season. Episode metadata now includes IndexNumber, ParentIndexNumber, SeriesId, SeasonId.

**Episode API enhancement**

Backend now returns additional episode metadata. Added IndexNumber (episode number), ParentIndexNumber (season number), SeriesId, and SeasonId for proper episode relationship tracking. Enables accurate next-episode detection for autoplay.

**Major code refactor**

Split monolithic `app.py` (1913 lines) into clean modular structure. New `app.py` entry point: 161 lines (92% reduction). Replaced custom logger with rsyslog-logger for production-grade logging. All components use dependency injection (no global variables). Improved maintainability and testability.

**Architecture refactor**

`src/__init__.py` (package init with version tracking). `src/emby_client.py` (240 lines, EmbyClient class encapsulating Emby API). `src/party_manager.py` (145 lines, replaces global watch_parties and hls_tokens). `src/utils.py` (190 lines, helper functions with dependency injection). `src/routes.py` (848 lines, all Flask HTTP routes). `src/socket_handlers.py` (624 lines, all SocketIO event handlers). `app.py` (161 lines, clean entry point with dependency injection).

**Dependency injection fixes**

Fixed `generate_party_code()` missing `watch_parties` parameter. Fixed `get_user_token()` calls missing `hls_tokens`, `config`, `logger` parameters. Fixed `validate_hls_token()` calls missing `hls_tokens`, `watch_parties`, `config`, `logger`, `item_id`. Replaced all `EMBY_SERVER_URL` references with `config.EMBY_SERVER_URL`. Replaced all `EMBY_API_KEY` references with `emby_client.api_key`.

**rsyslog-logger integration**

Replaced custom logger with rsyslog-logger package. Setup: `name="emby-watchparty"`, `log_file="logs/emby-watchparty.log"`, `log_level="INFO"`. Format: "rsyslog" with structured timestamps and log levels. Rotation: `max_size=20MB`, `backup_count=10`. Console and file output with independent log level control.

**Client-side (party.js)**

New state variables: `autoplayEnabled`, `currentEpisodeList`, `currentEpisodeIndex`, `currentSeasonId`, `currentSeriesId`. `loadSeasonEpisodes()` now stores episode list for autoplay tracking. `selectVideo()` tracks current episode index when playing episodes. Video `ended` event handler checks for next episode and triggers countdown. `startAutoplayCountdown()` displays 4-second timer overlay. `cancelAutoplay()` stops countdown and shows library instead. `hideAutoplayCountdown()` removes countdown overlay.

**UI / styling**

Added autoplay toggle button in stream controls. Added countdown overlay with episode name, timer, and cancel button. Autoplay toggle button with gradient styling (cyan/purple when ON, grey when OFF). Countdown overlay with blur backdrop and centered content. Animated countdown number with pulse effect (5rem font, gradient text). fadeIn animation for smooth countdown appearance.

---

## [1.1.1] - 2025-10-30

### Added
- Multi-theme system with 6 themes and localStorage persistence.
- Material Random theme with 152,000+ possible color combinations.
- WhatsApp-style chat interface with aligned bubbles.
- Theater media-center aesthetic (gold borders, red curtain effects).
- Video end detection (auto-shows library on natural finish).
- Auto-exit fullscreen when video ends.
- Library selection persists across page refreshes.

### Changed
- Fullscreen border removal moved from CSS to JavaScript for cross-browser reliability.

### Fixed
- Playback state reset on video end (no more position carry-over to next video).

### Technical details

**Multi-Theme System**

6 chooseable themes with localStorage persistence: Cyberpunk Theater (default), Material Random, Emby Green, Classic Dark, Minimal Light, Netflix Red. Theme selector with emoji icons on both index and party pages. Dedicated `static/js/theme.js` module for theme management. Automatic theme persistence across sessions.

**Material Random theme**

JavaScript-powered infinite color variations. 20 Material Design colors creating 152,000+ possible combinations. Randomize button (🎲) appears when Material theme is selected. Generates random gradients for primary/secondary/accent/gold colors. Real-time CSS custom property injection. Automatic style cleanup when switching to other themes.

**WhatsApp-style chat interface**

Messages from others aligned left with tertiary background. User's own messages aligned right with gradient bubble. Rounded chat bubbles (12px radius) with proper shadows. Username display in each message bubble. Flexbox-based responsive layout (70% max-width bubbles). Different bubble tail styles (bottom-left vs bottom-right).

**Theater media-center aesthetic**

Gold theater borders around video player (3px solid). Red curtain outline effect (8px rgba outline-offset). Marquee-style header with gradient top border. Cinema emojis throughout UI (🎬 🎭 🎞️ 💬). Spotlight shadow effects and glow on interactive elements. Inset shadows for depth and dimension on containers.

**Video end detection**

Detects natural video end via HTML5 `ended` event. Automatically shows library sidebar for all party members. Perfect for anime binge-watching workflow. System message in chat: "🎬 Video ended - Ready for next episode". Server broadcasts `video_ended` event via Socket.IO.

**Auto-exit fullscreen on end**

Automatically exits fullscreen when video ends naturally. Cross-browser support (Chrome, Firefox, Safari, Edge). Uses all vendor-prefixed fullscreen APIs. Prevents users being stuck in fullscreen after completion.

**Library selection persistence**

Saves current library/show/season selection to localStorage. Automatically restores last browsing position on page reload. Tracks three navigation levels: library items, season list, episode list. Stores IDs and names for accurate restoration. Graceful fallback to library root if saved state is invalid.

**Fullscreen border removal**

CSS pseudo-selectors (`:fullscreen`) weren't working across all browsers. JavaScript event listeners detect fullscreen state changes. Inline styles force border/outline/shadow removal (highest CSS specificity). All decorative elements (borders, shadows, outlines) hidden in fullscreen. Normal styles automatically restored when exiting fullscreen. Cross-browser event support (`fullscreenchange`, `webkitfullscreenchange`, etc.).

**Playback state reset on video end**

Video `ended` event now resets `currentPartyState` and `playbackStartTime` on client. Server resets `playback_state` to `{playing: false, time: 0}` when video ends. Fixes issue where seek position from previous video carried over to next selection.

---

## [1.1.0] - 2025-10-25

### Added
- Skip Intro button (uses Emby's intro markers).
- Intelligent PGS subtitle handling (auto burn-in for image subs).
- Independent VTT subtitle selection per user.
- Multi-audio track support re-enabled.

### Changed
- Subtitle workflow split: PGS server-side burn-in, text subtitles client-side VTT.
- Sync architecture overhauled: removed periodic-sync workaround.

### Fixed
- Mid-play join sync issues (no more video restarting to 0:00 for existing users when someone joins).
- False drift detection (no more random seeking and desyncing).
- Subtitle filtering and sync issues.
- UI layout issues (button squishing, subtitle container visibility).

### Technical details

**Skip Intro button**

Appears when intro markers are detected in Emby metadata. Positioned above video controls for easy access. Automatically shows/hides based on current playback position. Only works in normal viewing mode (limitation: not visible in fullscreen due to HTML5 video fullscreen constraints). Synced across all party members when clicked. Requires Emby API key to be configured for intro marker detection.

**Intelligent PGS subtitle handling**

Automatically detects PGS (Presentation Graphic Stream) subtitles. Burns in PGS/VobSub/DVD subtitles for pixel-perfect quality. Supports: pgssub, pgs, dvd_subtitle, dvdsub, vobsub formats. Prevents quality loss from PGS-to-text conversion. Works on both GPU and software encoding setups. PGS subtitles marked with `[Burned-in]` indicator in dropdown.

**Independent VTT subtitle selection**

All text-based subtitles automatically loaded as WebVTT tracks. Each party member can independently choose their subtitle language. Uses native browser CC button for subtitle selection. No transcode restarts needed for VTT subtitle changes. Subtitle dropdown automatically hides when only VTT subtitles available. PGS subtitles remain synced (burned-in), VTT selection is local-only.

**Subtitle workflow**

Dual-mode subtitle handling. PGS subtitles: server-side burn-in with `SubtitleMethod=Encode` (synced for all users). Text subtitles: client-side VTT loading with independent selection (local per user). Subtitle dropdown now only shows PGS options when available. Audio selection remains synced across all party members (requires transcode).

**Multi-audio track support**

Added back `AudioStreamIndex` parameter for proper audio track selection. Users can now switch between multiple audio tracks (e.g., different languages). Audio track changes are synced across all party members. Fixes issue where only the default audio track was available.

**Sync architecture overhaul**

Disabled 5-second periodic sync check (added in v1.0.5, no longer needed). Server now calculates accurate current time for new joiners. Client compensates for network and loading delays. Sync accuracy improved from ±4 seconds to sub-second precision. Simpler, more reliable sync mechanism.

**Mid-play join sync**

Fixed video restarting to 0:00 for existing users when someone joins. New joiners now start at correct position (e.g., 22 minutes, not 0:00). New joiners can immediately receive play/pause/seek commands. Set `isSyncing` flag before `loadVideo()` to prevent MANIFEST_PARSED reset. Use HLS.js `startPosition` config to load correct video segments immediately. Clear `isSyncing` in MANIFEST_PARSED to allow command processing. Server calculates elapsed time since last play/pause/seek for accurate sync. Client compensates for network + metadata loading delay (0.1-0.5s typical). Loading delay compensation capped at 2 seconds to prevent over-compensation.

**False drift detection**

Periodic sync was detecting false "drift" after pause/play. Example: pause at 496s, play again -> periodic sync thought 5s drift existed. Removed periodic sync -- play/pause/seek events provide sufficient sync. No more random video forwarding or seeking. Pause/play now works smoothly without desyncing users.

**Subtitle filtering and sync issues**

Fixed issue where mid-play joiners caused sync loops. Improved subtitle stream filtering logic. Better handling of default/forced subtitle selection. Removed invalid `SubtitleMethod=Drop` parameter (doesn't exist in Emby API). Fixed PGS subtitles appearing by default when "None" selected. Omit subtitle parameters entirely when None selected to prevent Emby auto-selection.

**UI layout issues**

Clear all subtitle tracks from video element when changing videos (prevents CC button clutter). Fixed Stop Video button stretching with `flex: 0 0 auto`. Changed subtitle container visibility from `display` to `visibility` toggle. Prevents Audio and Stop Video button from squishing together. Added max-width to stream controls for consistent spacing. Proper button positioning with `.stop-button-group` class.

**Code cleanup**

Removed 3 unused variables (`lastSyncTime`, `lastSeekBroadcast`, `seekBroadcastDelay`). Removed empty `socket.on('connected')` handler. Removed 12 development `console.log` statements. Reduced `party.js` from 1493 to 1459 lines. Fixed syntax error (extra closing brace in subtitle change handler).

---

## [1.0.6] - 2025-10-24

### Fixed
- Critical audio fix: videos now play with audio correctly.
- Video looping fix: videos no longer loop after 2-4 seconds.

### Changed
- Unified transcoding profile so all clients receive the same quality stream.

### Technical details

**Critical audio fix**

Added `AudioCodec=aac,mp3` parameter to force compatible audio transcoding. Added `TranscodingMaxAudioChannels=2` and `MaxAudioChannels=2` to ensure audio inclusion. Removed `AudioStreamIndex` parameter that was causing Emby to strip audio. Fixes issue where videos with FLAC or other lossless audio codecs had no sound. Dolby TrueHD support: now properly downmixes and transcodes to stereo AAC/MP3. HLS streams now properly transcode audio to browser-compatible formats.

**Video looping fix**

Added `BreakOnNonKeyFrames=True` to allow proper HLS segment generation. Added `VideoCodec=h264` to ensure maximum browser compatibility. Fixes issue where videos would play 2-4 seconds then restart. Works with both HEVC (H.265) and AVC (H.264) source videos.

**Unified transcoding profile**

All clients receive same quality stream. Video: H.264 (maximum compatibility). Audio: AAC or MP3 (handles FLAC, TrueHD, DTS, AC3, etc.). Channels: downmixed to stereo (2.0) from any multi-channel format. Single transcode per party = better performance and perfect sync.

**Enhanced HLS parameters**

`AudioCodec=aac,mp3` (supports both AAC and MP3 fallback). `VideoCodec=h264` (force H.264 for universal browser support). `BreakOnNonKeyFrames=True` (allow seeking to any point in video). `MaxAudioChannels=2` (downmix surround sound to stereo).

---

## [1.0.5] - 2025-10-23

### Added
- Periodic sync check (drift correction every 5 seconds).
- Browser-compatibility documentation in README.

### Changed
- Simpler 5-character invite codes (instead of 10-12 character URL-safe tokens).
- Tighter sync threshold (0.3s instead of 0.5s).
- Better browser-reload handling.

### Fixed
- Sync timing issues (drift accumulation, browser-reload sync, leave/reload desync).
- State tracking for authoritative server playback state.

### Technical details

**Periodic sync check**

New `startPeriodicSync()` function monitors playback timing. Automatically corrects sync drift greater than 0.3 seconds. Only syncs during active playback (skips when paused or seeking). Stops when video is stopped to conserve resources.

**Improved invite codes**

Changed from 10-12 character URL-safe tokens to simple 5-character codes. Uses uppercase letters and numbers only (A-Z, 2-9). Excludes confusing characters (0, O, 1, I, L) for clarity. Examples: `A3B7K`, `N2YS2`, `Y5HYP` instead of `abc123XyZ9aBc1`. Much easier to communicate over phone or in person.

**Tighter sync threshold**

Reduced from 0.5s to 0.3s for better accuracy. Fixed misleading comment (was "2 seconds" but code was 0.5s). More accurate synchronization between players. Reduces typical sync offset from ~4 seconds to under 0.3 seconds.

**Browser reload handling**

Changed condition from `time > 1` to `time >= 0`. Now syncs correctly at any video timestamp, including beginning. Starts periodic sync check immediately after reload.

**State tracking**

Added `currentPartyState` variable to track server's authoritative state. Updated on every play/pause/seek event from server. Used by periodic sync to detect and correct drift.

---

## [1.0.4] - 2025-10-22

### Added
- External subtitle support via WebVTT proxy endpoint.
- Automatic transcoding cleanup when video stops or changes.

### Changed
- Switched from burned-in to external subtitle delivery.
- Compact UI layout for video controls (side-by-side description + controls).

### Fixed
- Subtitle timeout issues (502 Bad Gateway on complex ASS/SSA subtitles).
- Resource management (HLS transcoding sessions properly terminated).

### Technical details

**External subtitle support**

New subtitle proxy endpoint `/api/subtitles/<item_id>/<media_source_id>/<index>` for serving WebVTT files. HTML5 `<track>` element integration for native browser subtitle rendering. `loadSubtitleTrack()` function for dynamic subtitle loading in frontend. `isTextSubtitleStream` flag in streams API response. `media_source_id` tracking across video selection and stream changes.

**Transcoding cleanup**

`stop_active_encodings()` method in EmbyClient. Calls DELETE `/Videos/ActiveEncodings` when video stops or changes. Prevents abandoned transcoding processes from consuming server resources.

**Subtitle delivery method**

Switched from burned-in to external subtitles. Removed `SubtitleMethod` parameter from HLS URLs. Subtitles now load as separate WebVTT files instead of being encoded into video. Enables instant subtitle switching without video reload.

**UI layout redesign**

Compact video controls layout. Video description and stream controls now displayed side-by-side. Audio, Subtitles, and Stop Video button placed in single horizontal row. Video description reduced to 2-line clamp for space efficiency. Added invisible label to Stop Video button for proper vertical alignment. Improved responsive flex layout for stream controls.

**Subtitle timeout issues**

Complex ASS/SSA subtitle files (e.g., "The Apothecary Diaries") no longer cause timeouts. Emby no longer forced to burn subtitles into video stream during transcoding. Significantly reduced CPU load during playback with subtitles.

---

## [1.0.3] - 2025-10-21

### Added
- Stop Video button (only visible to the video selector).
- HLS token validation system (per-user tokens tied to socket sessions).
- Comprehensive debug logging.
- Configuration template (`config.py.example`).

### Changed
- Library sidebar now hides for all users when video is selected.
- Default API rate limit increased to 1000 requests/minute.

### Fixed
- Token URL parameter construction (correct & vs ? separator).
- Tokens now correctly appended to all playlist types.

### Security
- Per-user HLS tokens with session validation.
- Token expiry tracking and cleanup.
- Tokens properly tied to socket session IDs.

### Technical details

**Stop Video button**

Allows the user who selected a video to stop it for all party members. Only visible to the video selector. Clears video player for all users. Backend validates only the selector can stop the video.

**HLS Token Validation System**

Per-user HLS tokens tied to socket session IDs. Token expiry tracking and automatic cleanup. Each user gets their own unique token for stream access. Prevents direct stream access bypass.

**Comprehensive debug logging**

Detailed debug logs for token generation and validation. Playlist URL rewriting visibility. Token assignment tracking per user. Comprehensive error reporting with full context (error type, URLs, tracebacks). Separate error handling for network errors vs internal errors.

**Configuration template**

Added `config.py.example` for easier setup. `config.py` is now untracked to prevent committing credentials. Users copy `config.py.example` to `config.py` and configure.

**Library sidebar behavior**

Library sidebar now hides for ALL users when video is selected (not just selector). Library sidebar automatically reopens when video is stopped. Consistent UI state across all party members.

---

## [1.0.2] - 2025-10-20

### Fixed
- Chat system messages cleaned up.
- Username display fix when server generates random username.

### Changed
- Chat only shows relevant user actions instead of technical status updates.

### Technical details

Removed verbose system messages (track counts, HLS ready, video loaded). Changed message format from "selected:" to "selected" for cleaner display. Fixed username variable not being set when server generates random username. Keep only essential messages: user selections and critical errors. Auto-capture username from server on join event.

---

## [1.0.1] - 2025-10-20

### Added
- Secure HLS proxy (Emby stays internal).

### Fixed
- Syntax error in `party.js:529` (extra closing brace).

### Technical details

**Secure HLS Proxy**

Major security improvement. Implement lightweight HLS proxy endpoints for master playlists and segments. Add URL rewriting to redirect playlist requests through Flask proxy. Only Flask app needs to be exposed; Emby stays on local network. Emby server no longer needs internet exposure.

---

## [1.0.0] - 2025-10-20

### Added
- Initial public release.

### Technical details

**Core features**

Create and join watch parties with shareable party codes. Synchronized video playback across all party members. Real-time chat functionality. Video library browsing and search. Season and episode selection for TV shows. Audio and subtitle track selection. Automatic playback synchronization. Random username generation for guests.

**Media server integration**

Direct integration with Emby media server. HLS streaming support with quality selection. Support for movies and TV shows. Direct transcoding through Emby.

**User interface**

Clean, modern web interface. Responsive design for desktop and mobile. Library sidebar with search. Video player with full controls. Chat panel with drag-to-resize. System messages for user actions.

**Technical foundations**

Flask backend with Socket.IO for real-time communication. HLS.js for adaptive bitrate streaming. Session-based party management. Custom logging system with rotation. Environment variable configuration.

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
