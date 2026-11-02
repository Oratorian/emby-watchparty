# Changelog

All notable changes to Emby Watch Party will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file contains the consolidated 3.0.0 release notes and a version history summary. The full beta changelogs and earlier stable release notes are preserved in [SUMMARY-OF-CHANGES.md](SUMMARY-OF-CHANGES.md).

### Special Thanks

Special thanks to **[QuackMasterDan](https://emby.media/community/index.php?/profile/1658172-quackmasterdan/)** for his dedication in testing and providing valuable feedback throughout development!

Thanks to **[wlowen](https://github.com/wlowen)** and **[JeslynMcKenzie](https://github.com/JeslynMcKenzie)** for testing, detailed bug reports, and providing mediainfo that helped track down the HEVC transcoding issues!

Thanks to **[Christian Gillinger](https://github.com/cgillinger)** for the "Refined Cyber" design language that the 2.0 visual refresh is built on -- the cyan/magenta/violet palette, glass surface treatment, chip/pill control language, animated LIVE badge, and centred system-message pill in chat all come from his mockup.

Special thanks to **[StealthyDruid](https://discord.com/users/458152893103603722)** and **[xyxxyxxy](https://discord.com/users/144553679058370560)** for their absolute dedication to testing every beta release of 2.x and 3.x. Their relentless testing, detailed bug reports and feedback helped eradicate nearly every bug along the way.

---

## [3.0.0] - 2026-11-02 - Director's Cut

Director's Cut brings the 3.0 beta cycle into one release: a typed backend, fuller library browsing, browser-aware playback, visible recovery paths and stricter deployment checks. It also includes the host/admin recovery fixes, current API documentation and dependency security updates below.

**Read the [2.x to 3.0 migration guide](docs/Migration-HowTo.md) before upgrading.** Back up the 2.x configuration and keep its image available until a real playback test succeeds. The [beta archive](SUMMARY-OF-CHANGES.md) preserves the detailed development history.

### Breaking Changes

- **Provider settings were renamed.** Replace `EMBY_SERVER_URL` or `JELLYFIN_SERVER_URL` with `MEDIA_SERVER_URL`, and `EMBY_API_KEY` or `JELLYFIN_API_KEY` with `MEDIA_SERVER_API_KEY`. Remove the old names, including empty declarations; there is no fallback, and keeping them prevents startup. `MEDIA_SERVER_TYPE` stays explicit as `emby` or `jellyfin`.
- **Production configuration is validated before serving the application.** Declare `BEHIND_PROXY` explicitly, with `TRUSTED_PROXY_CIDRS` when it is `true`. Production also requires a stable `SESSION_SECRET` of at least 32 characters, secure session cookies, explicit CORS origins, a media-server API key and HLS token validation. Invalid configuration leaves the container available for diagnosis with `setup_required` health and 503 readiness responses.
- **Legacy library, media and authentication REST routes were removed.** Third-party clients and scripts must use their `/api/v2` replacements. The web client already uses v2; the [migration guide](docs/Migration-HowTo.md) lists the removed routes and their replacements.
- **Source installations require Python 3.12 and a fresh virtual environment.** Recreate the environment and install the hash-locked requirements. Windows remains supported, with unsupported `uvloop` builds excluded by platform markers.
- **`SESSION_EXPIRY` now controls the actual idle session lifetime.** The default `86400` asks viewers to rejoin after 24 hours idle, replacing the previous hardcoded fourteen days. Rate limits are also enforced, so review the values carried forward from `config.json`.

### Added

- **Fuller library browsing.** Filters, grouped search, full-library A-Z navigation, richer title details, season and episode selectors, favourites, played state and playlist management bring more of the media-server library into Watch Party.
- **Playback follows each viewer's codec support.** Compatible browsers can keep HEVC video instead of forcing an H.264 encode for everyone, with H.264 fallback when needed.
- **Hosts control whether a party appears in Active Parties.** Parties start hidden; the host can change their visibility. Anyone holding the code can still join, so hiding a listing is not an access-control setting.
- **Migration and appliance deployment checks.** `python -m backend.migration_preflight` checks existing configuration without changing it. Compose, CasaOS and TrueNAS examples are generated from one deployment schema; Portainer uses the Compose example, and Unraid has a separate template.

### Fixed

- **Host state survives refresh and reconnect races.** A delayed authentication response no longer overwrites a newer session binding or host-reclaim event. Returning hosts see a recovery state while their presence is restored, and a delayed login response cannot restore privileges after another member has taken over.
- **Admin settings stay open after recoverable failures.** Temporary network/server errors and invalid HTTP 200 responses show an inline error with Retry. Only confirmed authentication failures return to login. Editing and saving wait for valid settings, failed saves preserve the draft, and late responses are ignored after the panel closes.

Reported by **[miakkia](https://github.com/miakkia)** in [#74](https://github.com/Oratorian/emby-watchparty/issues/74). The recovery paths are covered by regression tests and browser checks in Chromium and Firefox.

- **Playback and reconnect recovery carry forward the beta fixes.** iPhone and iPad receive the HLS range metadata they need, native playback respects ready checks, reconnecting viewers rejoin their party, and leaving releases their streams.
- **Failures stay visible and recoverable.** Rate-limited actions show a retry delay, refused chat text is preserved, failed library sections can be retried, and expired party links return viewers to the start page. Failed admin saves preserve the draft, including deployments that bind-mount `config.json` as a single file.
- **Upstream requests keep their timeout bounds.** Slow media-server calls no longer override the configured HTTP timeout with an unlimited wait.

### Changed

- **The backend uses typed, validated contracts and an application factory.** Inbound and outbound Socket.IO payloads are validated, REST and socket types are generated, and each test can construct an isolated application. Browser and fake-media-server tests cover playback, synchronization, reconnects and native HLS.
- **The detail view and admin controls are easier to use.** Compact season, episode and related-content controls stay close to the title, artwork no longer hides text, and rate-limit settings share consistent number and time-window controls.
- **The Socket.IO reference now covers the 3.0 protocol.** [`docs/SOCKET_API.md`](docs/SOCKET_API.md) documents all 21 inbound and 38 outbound events, with current payloads, host recovery, session binding, playback timing, visibility and rate limits. The examples are validated against the backend contracts.
- **Swagger and ReDoc now describe the responses the API returns.** Response schemas include serialized defaults, JSON errors, readiness failures, rate limits with `Retry-After`, image and subtitle bytes, and HLS range responses. HLS token and Range inputs are documented, and GET/HEAD operations have distinct IDs. Generated REST types follow the same contract, including optional validation-error fields and the literal rate-limit code. OpenAPI 3.1 validation covers all 44 paths and 48 operations, with runtime response regression tests.

### Security

- **Removed the unused Axios dependency.** The 3.0 API client already uses native `fetch`; removing Axios and its unused dependency chain resolves [#85](https://github.com/Oratorian/emby-watchparty/pull/85) without changing the active HTTP client or adopting Axios's compatibility changes.
- **`undici` 7.29.0 to 7.30.1** fixes TLS validation, cache isolation and denial-of-service advisories in frontend development/test tooling, through jsdom. The browser bundle's runtime dependencies are unchanged. Addresses [#80](https://github.com/Oratorian/emby-watchparty/pull/80); see the [upstream security fixes](https://github.com/nodejs/undici/releases/tag/v7.30.1).
- **Development HTTP clients updated to `httpx2` / `httpcore2` 2.12.0.** Fixes bounded response decompression, secure WebSocket proxying, request-header handling and event-stream buffering advisories. The separate runtime `httpx` dependency is unchanged. Addresses [#79](https://github.com/Oratorian/emby-watchparty/pull/79); see the [upstream fixes](https://github.com/pydantic/httpx2/releases/tag/v2.12.0).
- **`pytest` 8.4.2 to 9.0.3** fixes the Unix temporary-directory vulnerability [CVE-2025-71176](https://github.com/advisories/GHSA-6w46-j5rx-g56g). The development dependency floor is now 9.0.3, and universal lock generation preserves Windows dependencies and unsupported-platform exclusions. Addresses [#81](https://github.com/Oratorian/emby-watchparty/pull/81).
- **`multidict` 6.7.1 to 6.9.1** fixes the items-view set-operation reference leaks in [CVE-2026-104874](https://github.com/advisories/GHSA-54p9-h82j-f925), carried by the development aiohttp/yarl dependencies. Addresses [#82](https://github.com/Oratorian/emby-watchparty/pull/82).
- **HLS and administrator credentials retain their authorization boundaries.** HLS requests require a party-bound session and matching stream token; host ownership uses a private grant, and administrator access tokens stay server-side. Playlist URLs are validated before rewriting, and access logs redact HLS tokens.
- **The runtime image applies pending Debian security updates at build time.** This carries the beta4 image hardening into the stable release.
- **`aiohttp` 3.14.3 to 3.14.4** fixes eight security advisories in development and test tooling, including request handling and cookie isolation issues. The development dependency floor is now 3.14.4, with the required `yarl` update from 1.24.5 to 1.25.1. Runtime dependencies are unchanged, and the universal lock retains Windows support. Addresses [#78](https://github.com/Oratorian/emby-watchparty/pull/78); see the [upstream security fixes](https://github.com/aio-libs/aiohttp/releases/tag/v3.14.4).
- **`certifi` 2026.7.22 to 2026.10.23** removes trust in the compromised emSign certificate chain described in [GHSA-6q48-6c7w-9gw2](https://github.com/advisories/GHSA-6q48-6c7w-9gw2), while retaining unaffected roots restored after the initial fix. Runtime and development locks retain their platform rules, including Windows dependencies and the exclusion of unsupported `uvloop` builds. Addresses [#77](https://github.com/Oratorian/emby-watchparty/pull/77).
- **The unused `follow-redirects` dependency was removed with Axios.** The 3.0 branch had already carried the sensitive-header filtering fix from [#75](https://github.com/Oratorian/emby-watchparty/pull/75), including the [cross-realm array bypass](https://github.com/follow-redirects/follow-redirects/security/advisories/GHSA-mrwp-f3q8-3g9p); the dependency is no longer needed by the active client.
- **`vite` 7.3.6 to 7.3.7** fixes [development-server file access](https://github.com/vitejs/vite/security/advisories/GHSA-rq7h-c2jc-7f22), [script execution in custom HTML middleware](https://github.com/vitejs/vite/security/advisories/GHSA-9jrq-w75r-8gcw), and [bundled editor-launching vulnerabilities](https://github.com/vitejs/vite/pull/23654). The Vite dependency range now starts at `^7.3.7`. Carried over from [#76](https://github.com/Oratorian/emby-watchparty/pull/76).

---

## Version History Summary

- **[v3.0.0](#300---2026-11-02---directors-cut)** (2026-11-02): Director's Cut release, combining the 3.0 beta cycle with host/admin recovery, current API documentation and dependency security updates. Requires the 2.x migration steps.
- **[v3.0.0-beta4](SUMMARY-OF-CHANGES.md#300-beta4---2026-09-11---directors-cut)** (2026-09-11): Provider variable migration, removal of legacy REST routes, API-key-aware readiness, bind-mounted configuration save fixes and build-time Debian security updates.
- **[v3.0.0-beta3](SUMMARY-OF-CHANGES.md#300-beta3---2026-08-13---directors-cut)**  (2026-08-13): Library parity, the detail-view UX pass, host-controlled party visibility, and a test-suite audit that found two real bugs on a green suite. Carries the beta2 work, which never shipped as its own image. Image-only, does not move `:latest`.
- **[v3.0.0-beta2](SUMMARY-OF-CHANGES.md#300-beta2---2026-08-13---directors-cut)** (2026-08-13): Visible rate-limit errors, migration preflight, generated deployment examples, library work and codec-aware HEVC playback. Never published separately; included in beta3.
- **[v3.0.0-beta1](SUMMARY-OF-CHANGES.md#300-beta1---2026-08-05---directors-cut)**  (2026-08-05): Architecture release, first beta -- typed socket/REST contracts with runtime validation, application factory, production readiness gate, and a fake-Emby test suite. Configuration is environment-only. The 2.1.0 authorization work is re-established, and the audit backlog is closed. Does not move `:latest`.
- **[v2.1.0](SUMMARY-OF-CHANGES.md#210---2026-08-03---midnight-premiere)**  (2026-08-03): Security -- `/hls` now session-gated with a cookie/token party match, and the Emby admin token moved out of the session cookie.
- **[v2.0.2](SUMMARY-OF-CHANGES.md#202---2026-08-01---midnight-premiere)**  (2026-08-01): HLS token rewriting fixed for CRLF playlists (playback stuck buffering at 0:00) + first HLS proxy tests.
- **[v2.0.1](SUMMARY-OF-CHANGES.md#201---2026-07-14---midnight-premiere)**  (2026-07-14): Democratic playback control (any member can play/pause/seek) + sync-guard fixes.
- **[v2.0.0](SUMMARY-OF-CHANGES.md#200---2026-07-11---midnight-premiere)**  (2026-07-11): Official release after 6 months of beta.
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
