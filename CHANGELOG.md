# Changelog

All notable changes to Emby Watch Party will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

This file contains unreleased changes, the consolidated 3.0.0 release notes and a version history summary. The full beta changelogs and earlier stable release notes are preserved in [SUMMARY-OF-CHANGES.md](SUMMARY-OF-CHANGES.md).

### Special Thanks

Special thanks to **[QuackMasterDan](https://emby.media/community/index.php?/profile/1658172-quackmasterdan/)** for his dedication in testing and providing valuable feedback throughout development!

Thanks to **[wlowen](https://github.com/wlowen)** and **[JeslynMcKenzie](https://github.com/JeslynMcKenzie)** for testing, detailed bug reports, and providing mediainfo that helped track down the HEVC transcoding issues!

Thanks to **[Christian Gillinger](https://github.com/cgillinger)** for the "Refined Cyber" design language that the 2.0 visual refresh is built on -- the cyan/magenta/violet palette, glass surface treatment, chip/pill control language, animated LIVE badge, and centred system-message pill in chat all come from his mockup.

Special thanks to **[StealthyDruid](https://discord.com/users/458152893103603722)** and **[xyxxyxxy](https://discord.com/users/144553679058370560)** for their absolute dedication to testing every beta release of 2.x and 3.x. Their relentless testing, detailed bug reports and feedback helped eradicate nearly every bug along the way.

---

## [Unreleased]

### Added

- **Movie and show overviews can play a background preview for up to two minutes.** Movies use a random section of the selected film; shows use a random episode. Previews start automatically muted, with unmute and pause controls. Browsers that block autoplay offer a Play preview button. The preview uses a separate, low-bandwidth stream without changing party playback or watched progress, and stops when the overview is hidden or closed. Reduced-motion and data-saving preferences retain the still backdrop until Play is selected.
- **The emoji button opens a chat menu with emojis and appearance settings.** The menu works with hover, keyboard or touch. Viewers can choose the default font or bundled Rajdhani, Oxanium and Space Grotesk webfonts, adjust chat text from 12 to 24 pixels, preview changes and reset the appearance. Preferences stay in each browser; the open-source fonts are served locally.
- **The desktop chat panel can be resized by dragging its divider.** Width limits preserve space for the video or library. Arrow keys also adjust the width, a double-click restores the default, and each browser remembers its preferred width.

### Fixed

- **Refreshing a party restores the saved username and host session without needing a second reload.** HTTP session binding completes before the socket handshakes, and returning development hosts retain their existing host grant. Join failures show their error and retain the entered name for Retry.
- **Library browsing fills the main area and hides the player again.** The chat divider no longer pins the library to a narrow column. The active player stays mounted, so closing the library reveals the same stream.
- **Docker initializes missing or blank runtime configuration files with `{}` before startup.** Initialization writes through single-file bind mounts and preserves existing nonblank settings. The image also includes a valid `config.json` mount target. Deployment instructions initialize missing or empty host files without overwriting populated configurations; source installations and explicit migration-preflight commands retain their existing behavior.

---

## [3.1.0] - 2026-11-06 - Director's Cut

### Added

- **Completed language packs can be submitted to the EWP Discord team through a maintainer-hosted relay.** The creator requires complete valid coverage, checks the relay's catalog revision, preserves drafts and submission receipts, and handles rate limits and uncertain delivery without automatic resends. The public relay endpoint is configured in the creator; webhook credentials remain on the relay.
- **A browser language-pack creator is available through GitHub Pages.** Use the [online creator](https://ewp-language.mahesvara.cloud/) to edit the English messages, check placeholders, save or recover drafts, open existing packs, and export a validated ZIP. The site lives in `docs/`; project documentation moved to `documentations/`.
- **Community language packs can be installed at runtime.** Admins can download a translation template, upload or replace a language ZIP, and remove installed packs. Validated packs persist in the data volume and appear in viewers' language selectors without a rebuild or restart. Partial translations fall back to English; removing a German override restores the bundled translation. Archive bounds, known message keys and placeholders are checked before atomic installation. Public language discovery and admin operations are documented in OpenAPI and included in generated REST types. Extends [#87](https://github.com/Oratorian/emby-watchparty/issues/87).
- **English and German UI localization with vue-i18n.** Watch Party detects the browser language and lets each viewer save a language preference. Party controls, library browsing, title details, admin settings and recovery dialogs use complete translated messages with placeholders and plurals. Known Emby and Jellyfin filter labels are translated while request values and media metadata stay unchanged. Longer filter labels wrap on narrow screens. Initial German translations contributed by [timokohlbrecher-collab](https://github.com/timokohlbrecher-collab) in [#87](https://github.com/Oratorian/emby-watchparty/issues/87).
- **[The Watch Party Story](documentations/The-Watch-Party-Story.pdf)** collects the project's history in a first-person memoir, drawing on recovered 1.x history, 1,008 surviving commit messages, changelog archives and community contributions through 3.0.0.

### Changed

- **Release publishing reuses successful Validate results for the exact release commit.** A lightweight gate checks the current CI attempt and CI Gate, waits for validation already running, and blocks publishing when validation is missing or unsuccessful. The publishing checkout stays pinned to the validated commit, with the existing release approval step.
- **Building the frontend from source now requires Node 22.12 or newer**, as required by the patched vue-i18n dependency. Docker and CI continue to use Node 24.
- **The landing-page language selector is centered below the create/join cards.** Admin headers wrap on narrow screens, and long community language names stay within the viewport.
- **Browser tests use disposable configuration and data.** The test backend isolates uploads, identities and settings without loading the operator's `.env` or writing their runtime configuration and logs. Relay upload tests receive real HTTP uploads and compare ZIP contents instead of relying on WebKit's incomplete intercepted file bodies.

### Fixed

- **WebKit language controls no longer overflow or swallow the first submission click.** Long community language names stay within the native selector, and leaving an unchanged language-code field does not interrupt the creator's submit button.
- **The landing-page badge now follows the frontend version**, replacing the stale Watch Party 2.0 label. The browser title uses Director's Cut in both bundled languages and the initial HTML.
- **The creator's translation-sharing panel stays beside the editor while scrolling** on desktop and tablet, keeping submission status and receipts visible. Mobile screens stack it below the editor.
- **Generated Pages files stay consistent across Windows and Linux.** Normalized line endings prevent false CI drift failures, and page-title changes are generated from the source locales into the English catalogs.

### Security

- **Development tooling uses patched `minimatch` 11.0.5 and `glob` 14.0.4.** Overrides remove affected transitive matcher versions for [GHSA-g3hv-75wg-m249](https://github.com/isaacs/minimatch/security/advisories/GHSA-g3hv-75wg-m249) and pair the formatter with a compatible glob release, also fixing [GHSA-3g3m-2fjr-6pw4](https://github.com/advisories/GHSA-3g3m-2fjr-6pw4). Compatibility checks cover file matching, Windows paths, EditorConfig and the formatter CLI.
- **Language-pack file operations verify their resolved storage paths.** Reads, replacements and removals reject pack-file symlinks and paths outside the language directory. API errors return curated validation messages instead of internal exception details.
- **Release validation explicitly limits its GitHub token to `contents: read` and `actions: read`.** The validation gate can inspect CI results without publishing permissions; the publishing job retains its required release permissions.
- **Vue and its matching runtime/compiler packages updated from 3.5.39 to 3.5.42**, fixing unsafe carriage returns in server-rendered attribute names ([GHSA-g2v6-rqmx-r4w6](https://github.com/advisories/GHSA-g2v6-rqmx-r4w6)). The dependency floor now starts at the patched version.
- **`source-map-js` updated from 1.2.1 to 1.2.2**, fixing denial of service from invalid indexed source-map offsets ([GHSA-68fv-2mgg-jv7q](https://github.com/advisories/GHSA-68fv-2mgg-jv7q)).
- **`shell-quote` updated from 1.10.0 to 1.12.0** in frontend build tooling, fixing command injection when a line terminator follows a comment token ([GHSA-pqg4-j6r4-53mv](https://github.com/advisories/GHSA-pqg4-j6r4-53mv)).

---

## [3.0.0] - 2026-11-02 - Director's Cut

Director's Cut brings the 3.0 beta cycle into one release: a typed backend, fuller library browsing, browser-aware playback, visible recovery paths and stricter deployment checks. It also includes the host/admin recovery fixes, current API documentation and dependency security updates below.

**Read the [2.x to 3.0 migration guide](documentations/Migration-HowTo.md) before upgrading.** Back up the 2.x configuration and keep its image available until a real playback test succeeds. The [beta archive](SUMMARY-OF-CHANGES.md) preserves the detailed development history.

### Breaking Changes

- **Provider settings were renamed.** Replace `EMBY_SERVER_URL` or `JELLYFIN_SERVER_URL` with `MEDIA_SERVER_URL`, and `EMBY_API_KEY` or `JELLYFIN_API_KEY` with `MEDIA_SERVER_API_KEY`. Remove the old names, including empty declarations; there is no fallback, and keeping them prevents startup. `MEDIA_SERVER_TYPE` stays explicit as `emby` or `jellyfin`.
- **Production configuration is validated before serving the application.** Declare `BEHIND_PROXY` explicitly, with `TRUSTED_PROXY_CIDRS` when it is `true`. Production also requires a stable `SESSION_SECRET` of at least 32 characters, secure session cookies, explicit CORS origins, a media-server API key and HLS token validation. Invalid configuration leaves the container available for diagnosis with `setup_required` health and 503 readiness responses.
- **Legacy library, media and authentication REST routes were removed.** Third-party clients and scripts must use their `/api/v2` replacements. The web client already uses v2; the [migration guide](documentations/Migration-HowTo.md) lists the removed routes and their replacements.
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
- **The Socket.IO reference now covers the 3.0 protocol.** [`documentations/SOCKET_API.md`](documentations/SOCKET_API.md) documents all 21 inbound and 38 outbound events, with current payloads, host recovery, session binding, playback timing, visibility and rate limits. The examples are validated against the backend contracts.
- **Swagger and ReDoc now describe the responses the API returns.** Response schemas include serialized defaults, JSON errors, readiness failures, rate limits with `Retry-After`, image and subtitle bytes, and HLS range responses. HLS token and Range inputs are documented, and GET/HEAD operations have distinct IDs. Generated REST types follow the same contract, including optional validation-error fields and the literal rate-limit code. OpenAPI 3.1 validation covers all 44 paths and 48 operations, with runtime response regression tests.

### Security

- **`postcss-selector-parser` 7.1.4 to 7.1.7** fixes the flat-selector CPU exhaustion issue [CVE-2026-104844](https://github.com/advisories/GHSA-rj75-hqrm-r3gf) in frontend tooling. Addresses [#83](https://github.com/Oratorian/emby-watchparty/pull/83).
- **`brace-expansion` updated to 2.1.7 and 5.0.12** across all four locked copies, fixing [CVE-2026-102277](https://github.com/advisories/GHSA-q2hr-2g5m-vwhr) without changing the dependency major lines. Addresses [#84](https://github.com/Oratorian/emby-watchparty/pull/84).
- **Vitest and its coverage tooling updated to 4.1.12.** The matched versions include fixes for [manual mock code injection](https://github.com/advisories/GHSA-qxg6-89mg-rqv8) and the [Windows redirect-allowlist bypass](https://github.com/advisories/GHSA-xp26-3454-mjgp), both still affecting the 4.1.11 target in [#86](https://github.com/Oratorian/emby-watchparty/pull/86). Development dependency floors now start at 4.1.12.
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
