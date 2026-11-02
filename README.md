# Emby Watch Party

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12](https://img.shields.io/badge/python-3.12-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![Vue 3](https://img.shields.io/badge/Vue-3-42b883.svg?logo=vue.js&logoColor=white)](https://vuejs.org/)
[![Docker Image](https://img.shields.io/badge/ghcr.io-oratorian%2Femby--watchparty-2496ED.svg?logo=docker&logoColor=white)](https://github.com/Oratorian/emby-watchparty/pkgs/container/emby-watchparty)
[![GitHub release](https://img.shields.io/github/release/Oratorian/emby-watchparty.svg)](https://github.com/Oratorian/emby-watchparty/releases)
[![GitHub stars](https://img.shields.io/github/stars/Oratorian/emby-watchparty.svg)](https://github.com/Oratorian/emby-watchparty/stargazers)
[![Discord](https://img.shields.io/discord/1311999162098782229?logo=discord&logoColor=white&label=discord&color=5865F2)](https://discord.gg/RWUpxq9xsA)

A synchronized watch-party frontend for Emby and Jellyfin: watch together while your media server stays on your internal network. Any member with an account on the configured server can become the room's host; other viewers join as spectators without a media-server account.

This branch contains 3.x. The [watchparty2 branch](https://github.com/Oratorian/emby-watchparty/tree/watchparty2) preserves the 2.x source and documentation. Read the [migration guide](docs/Migration-HowTo.md) before moving an existing 2.x deployment to 3.0.

---

## Table of contents

- [Support development](#support-development)
- [Special thanks](#special-thanks)
- [Discord](#discord)
- [Documentation](#documentation)
- [Features](#features)
- [Browser compatibility](#browser-compatibility)
- [Setup](#setup)
  - [Prerequisites](#prerequisites)
  - [Manual installation](#manual-installation)
  - [Docker installation](#docker-installation)
- [Usage](#usage)
  - [Creating a watch party](#creating-a-watch-party)
  - [Joining a watch party](#joining-a-watch-party)
  - [In-party controls](#in-party-controls)
- [Configuration](#configuration)
  - [.env](#env)
  - [Admin panel](#admin-panel)
- [Architecture](#architecture)
- [API endpoints](#api-endpoints)
- [Troubleshooting](#troubleshooting)
- [Security notes](#security-notes)
- [License](#license)
- [Contributing](#contributing)
- [Acknowledgments](#acknowledgments)
- [Educational use notice](#educational-use-notice)

---

### Support development

If Emby Watch Party has saved you from the hell of trying to coordinate "3, 2, 1, play" over Discord, consider buying me a coffee:

**[ko-fi.com/jedziah](https://ko-fi.com/jedziah)**

Every tip helps fund the hardware and the late nights reverse-engineering Emby's HLS pipeline.

---

### Special thanks

Special thanks to **[QuackMasterDan](https://emby.media/community/index.php?/profile/1658172-quackmasterdan/)** for his dedication in testing and providing valuable feedback throughout development.

Thanks to **[wlowen](https://github.com/wlowen)** and **[JeslynMcKenzie](https://github.com/JeslynMcKenzie)** for testing, detailed bug reports, and providing mediainfo that helped track down the HEVC transcoding issues.

Special thanks to **[StealthyDruid](https://discord.com/users/458152893103603722)** and **[xyxxyxxy](https://discord.com/users/144553679058370560)** for their absolute dedication to testing every beta release of 2.x and 3.x. Their relentless testing, detailed bug reports and feedback helped eradicate nearly every bug along the way.

---

### Discord

https://discord.gg/RWUpxq9xsA

---

## Documentation

- **[Project wiki](https://github.com/Oratorian/emby-watchparty/wiki)** - hardware, deployment, troubleshooting, and FAQ
- **[Migration guide](docs/Migration-HowTo.md)** - upgrade path from 2.1.x to 3.0
- **[Appliance deployment](docs/deployment/appliance-migration.md)** - Compose, CasaOS, Portainer, and TrueNAS setup, diagnosis, update, and rollback; the maintainer's separate Unraid templates repository is indexed by Community Apps through `TemplateURL`
- **[Socket.IO API](docs/SOCKET_API.md)** - developer reference for the Socket.IO event protocol
- **OpenAPI reference** - `GET /docs` (Swagger UI) or `GET /redoc` on a running instance
- **[CHANGELOG.md](CHANGELOG.md)** - consolidated 3.0.0 release notes, upgrade requirements and version history summary
- **[SUMMARY-OF-CHANGES.md](SUMMARY-OF-CHANGES.md)** - full 3.0 beta changelogs and earlier stable release notes, with links to the older 2.0 beta log and 3.0 technical analysis
- **[Emby quirks we learned the hard way](docs/Emby%20quirks%20we%20learned%20the%20hard%20way.md)** - Why 2.0 came to be.

## Features

- **Secure proxy architecture**: your Emby or Jellyfin server stays on the local network; only the WatchParty app is exposed
- **FastAPI + Vue 3 + TypeScript stack**: async end-to-end, typed OpenAPI docs at `/docs` and `/redoc`, single uvicorn process serves backend + compiled SPA
- **Real-time sync with drift correction**: any party member can play, pause or seek; the shared party clock keeps independent streams aligned, with progress reports from the video selector anchoring drift correction
- **Late-joiner voting flow**: existing users vote to admit mid-playback joiners; a passing vote restarts on a PTS-aligned segment 0 so everyone lands together
- **Host-provider auth model**: UNLOCKED / PLAYING-ONLY / LOCKED states around the authenticated media-server host, with ownership recovery for quick refreshes
- **Per-user playback sessions**: audio, subtitles, quality and media version are personal, with separate media-server streams for each viewer
- **Multi-version playback**: each viewer can switch between available media versions during playback, such as theatrical/director's cut or 1080p/4K sources
- **Bitrate-granular quality menu**: mirrors Emby's own per-resolution table, with admin-side toggles for exposed resolutions and bitrates
- **Unified subtitles**: text subs via side-channel proxy, image (PGS) subs burned in per-user, both surfaced in one dropdown
- **Resume, jump-to-timestamp, and binge auto-advance**: Continue Watching prompt from Emby `UserData`, absolute-timestamp seek input, and end-of-episode countdown with room-wide Cancel
- **Rooms, chat, and identity**: 5-character party codes, live chat with a mobile slide-over, custom avatars (upload / Gravatar / monsterid fallback) recoverable via 3-word codes
- **Refined Cyber UI**: cyan/magenta/violet palette, glass surfaces, chip/pill controls, animated LIVE badge, iOS-style A-Z library jump bar
- **Reverse-proxy ready**: `APP_PREFIX` wired end-to-end so one Docker image sits behind any subpath (`https://example.com/watchparty/...`)
- **Admin panel**: runtime settings editable from `/admin`, including the in-party modal; most changes apply immediately, while file-logging changes require restart
- **Reload-as-rejoin + healthchecks**: refresh in an active party rejoins via persistent `client_id`; `/api/health` reports liveness and `/api/ready` verifies the media server is reachable **and** that the configured API key is accepted; rsyslog-style logging with rotation

## Browser compatibility

The desktop browser targets are Chrome, Edge, Firefox, Safari and Brave. Mobile targets are Safari on iOS and Chrome on Android. Codec support and native fullscreen subtitle behaviour depend on the browser, operating system and source media.

CI exercises Chromium, Firefox and desktop WebKit. Chromium covers the full fake-media-server playback journey; Firefox adds host/admin recovery checks, and desktop WebKit covers the cross-engine smoke suite. Native HLS checks run with the iOS WebKit project on macOS. These checks do not replace a playback test on your viewers' devices.

**Known issue:** Brave on iOS has been reported to hide subtitles in fullscreen while normal-view subtitles still work. Use Safari on iOS when affected.

## Setup

### Prerequisites

- An Emby or Jellyfin server reachable from the Watch Party backend. The media server does not need to be exposed to the internet.
- A dedicated administrative API key from that server. Host credentials are supplied through the in-app login flow, rather than stored in `.env`.
- A Watch Party URL reachable by your viewers, with HTTPS for production deployments.
- **For Docker installs:** Docker Engine and Docker Compose v2.
- **For manual installs:** Python **3.12.x**, Node.js matching **`^20.19.0 || >=22.12.0`**, and npm. The official frontend build and CI use Node 24.

### Manual installation

Use a fresh checkout and Python 3.12. Existing 2.x installations need the [migration steps](docs/Migration-HowTo.md), including a fresh virtual environment while preserving their configuration and data.

1. **Create and activate the virtual environment.**

   Linux/macOS:

   ```sh
   python3.12 -m venv .venv
   . .venv/bin/activate
   ```

   Windows PowerShell, with Python 3.12 selected as `python`:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

   Install the backend dependencies with hash verification:

   ```sh
   python -m pip install --require-hashes -r requirements.txt
   ```

2. **Build the frontend.** Vite writes the bundle to `backend/static/`:

   ```sh
   cd frontend
   npm ci
   npm run build
   cd ..
   ```

   For hot-reload development and browser tests, see [frontend/README.md](frontend/README.md).

3. **Configure the backend.** For a new installation, copy `.env.example` to `.env`:

   ```sh
   cp .env.example .env
   ```

   PowerShell equivalent:

   ```powershell
   Copy-Item .env.example .env
   ```

   The example is a **production template**. Fill in `MEDIA_SERVER_TYPE`, `MEDIA_SERVER_URL`, `MEDIA_SERVER_API_KEY`, a stable `SESSION_SECRET`, and `CORS_ALLOWED_ORIGINS`. Uncomment and set `SESSION_COOKIE_SECURE=true` and `BEHIND_PROXY=true` or `false`; a proxy deployment also needs its actual `TRUSTED_PROXY_CIDRS`. Keep HLS token validation enabled.

   Generate the session secret once with `openssl rand -hex 32`, or with Python:

   ```sh
   python -c "import secrets; print(secrets.token_hex(32))"
   ```

   For local plain HTTP, use `APP_ENV=development` and `SESSION_COOKIE_SECURE=false`. Development relaxes production-only requirements, but provider, URL, port, prefix and proxy settings must still be valid. Browsing and playback need a reachable media server and working credentials.

4. **Run the application** from the repository root with the environment active:

   ```sh
   python -m backend.app
   ```

5. Open `http://localhost:5000/`. With `APP_PREFIX=/watchparty`, use `http://localhost:5000/watchparty/`. API documentation stays at hostname-root `/docs` and `/redoc`, with the schema at `/openapi.json`.

### Docker installation

Upgrading from 2.1.x requires the [3.0 migration guide](docs/Migration-HowTo.md).
Back up `.env`, the effective Compose/container configuration, `config.json`,
`data/`, `images/avatars/`, and every volume mapping. Keep the old image and
complete backup until login, playback, seeking, subtitles and reconnects pass a real test.

**Choose the image tag deliberately:**

| Tag | Purpose |
| --- | --- |
| `:2` | Stable 2.x line |
| `:3`, `:3.0` | Stable 3.x line, available once its first stable image is published |
| `:3.0.0` | Exact 3.0.0 release, available once published |
| `:devel`, `:nightly` | Moving 3.x prerelease images |
| `:latest` | Latest stable release; it can move between major versions |

The [generated Compose example](docker-compose.yml.example) currently selects
`:devel`. Before a stable 3.x image is published, use that prerelease for testing
or build this checkout locally with `docker build -t emby-watchparty:local .`
and set the copied Compose service's `image:` to `emby-watchparty:local`.
Changing a Git branch does not publish an image.

For the published prerelease:

```sh
docker pull ghcr.io/oratorian/emby-watchparty:devel
```

For a **new installation**, copy `docker-compose.yml.example` to
`docker-compose.yml` and `.env.example` to `.env`. Existing installations
should edit their copies using the migration guide.

Fill the production settings described above. In the copied Compose file,
**uncomment the `SESSION_COOKIE_SECURE` and `BEHIND_PROXY` environment entries**.
Setting them only in Compose's `.env` does not pass them into the container
while those mappings remain commented out.

Create persistent directories and `config.json` before the first start.
Keep an existing `config.json` unchanged; a new file must contain `{}`,
rather than be empty or a directory.

Linux/macOS:

```sh
mkdir -p data images/avatars logs
[ -f config.json ] || echo {} > config.json
```

Windows PowerShell:

```powershell
New-Item -ItemType Directory -Force data, images/avatars, logs | Out-Null
if (-not (Test-Path config.json)) { Set-Content config.json '{}' }
```

Run the read-only preflight against the exact candidate environment and volumes,
then start only after resolving its errors and required actions:

```sh
docker compose run --rm --no-deps emby-watchparty python -m backend.migration_preflight --root /app --target production --deployment docker
docker compose up -d emby-watchparty
```

Invalid production configuration keeps the process reachable for diagnosis:
`/api/health` reports `setup_required`, `/api/ready` returns 503, and stderr names
the failing settings. Both API paths include `APP_PREFIX` when configured.

The supplied Compose artifacts set the container bind and port to
`0.0.0.0:5000`. To expose another host port, change only the left side of
the `HOST_PORT:5000` mapping.

If you prefer `docker run`, this POSIX-shell example uses the same storage layout
and prerelease tag. Set the production values in `.env` first, or use the local
development configuration for plain HTTP:

```sh
docker run -d \
  --name emby-watchparty \
  -p 5000:5000 \
  --env-file .env \
  -e WATCH_PARTY_BIND=0.0.0.0 \
  -e WATCH_PARTY_PORT=5000 \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/images/avatars:/app/images/avatars" \
  -v "$(pwd)/config.json:/app/config.json" \
  -v "$(pwd)/logs:/app/logs" \
  ghcr.io/oratorian/emby-watchparty:devel
```

| Host path | Container path | Purpose |
| --- | --- | --- |
| `./data` | `/app/data` | Persistent avatar database |
| `./images/avatars` | `/app/images/avatars` | Uploaded avatar images |
| `./config.json` | `/app/config.json` | Runtime admin settings |
| `./logs` | `/app/logs` | Optional mount to retain logs across recreation; file logging is enabled by default |

Keep `SESSION_SECRET` stable across restarts. A missing secret creates an
ephemeral key in development, while production rejects it. Run one application
process/worker because party state, sessions, rate limits, background tasks and
HLS tokens are process-local.

Boot settings come from the environment or `.env` and require restart.
Runtime settings live in `config.json` and the admin panel; most apply immediately,
while file-logging changes require restart. Platform guides and validation steps
are indexed in the [appliance deployment guide](docs/deployment/appliance-migration.md).

## Usage

### Creating a watch party

The default (`REQUIRE_LOGIN=false`):
1. Click **"Create Party"** on the home page (no login required)
2. Share the party code or URL with your friends
3. Inside the party, click **"Login to Become Host"** with your media-server credentials. This unlocks the library for everyone in the room. Spectators can join without a media-server login.
4. Browse the library and select a video
5. Everyone in the room will be synchronized

With `REQUIRE_LOGIN=true` (set from the admin panel):
1. Click **"Create Party"** and supply credentials for the configured Emby or Jellyfin server
2. The creator becomes host atomically; the party starts UNLOCKED
3. Share the code; spectators join with no login prompt
4. Browse, pick, watch

In both modes, when the host disconnects mid-playback the in-flight video keeps streaming until it ends naturally (PLAYING-ONLY state). The library re-locks immediately; any member can click "Login to Become Host" to unlock it again.

### Joining a watch party

1. Click **"Join Watch Party"** on the home page (or open a shared URL)
2. Enter the party code if needed
3. Enter your username
4. Start watching together!

If you join **before** a video has been selected, you land directly in the party. If you join **while a video is already playing**, the existing users will see a vote modal asking whether to restart the video from the beginning so you can join in sync. See the [project wiki](https://github.com/Oratorian/emby-watchparty/wiki) for full details of the late-joiner vote flow.

### In-party controls

- **Browse library**: use the sidebar to browse the configured media server's libraries, movies and TV shows
- **Select video**: click on any video to start watching it with the group
- **Video controls**: any user can play, pause, or seek - all users will sync
- **Audio, subtitles, quality and media version**: each viewer can change their own settings during playback without pausing the room or starting a shared ready check
- **Chat**: use the chat box at the bottom to communicate with other viewers
- **Leave**: click the "Leave" button to exit the watch party

## Configuration

Configuration is split into two tiers:

1. **Boot-essential settings** come from environment variables or `.env` and require restart.
2. **Runtime settings** are editable from the **admin panel** at `/admin`, using administrator credentials for the configured media server. Most changes apply immediately; file-logging changes are saved with a restart-required indication.

Boot precedence is exact: **process environment -> `.env` -> defaults**. Process environment and `.env` are one explicit-operator tier, with process values winning. Reading `.env` does not mutate the running process environment.

### When boot configuration is invalid

The process stays reachable but serves nothing. Normal API, Socket.IO, HLS, admin and application routes return `503`; liveness returns HTTP `200` with `status: setup_required`, and readiness returns `503` with the same status, so an orchestrator can tell "misconfigured" from "dead" without restart-looping the container.

The failing fields are named on stderr in a framed banner, and again through the application logger:

```
========================================================================
  Emby Watch Party cannot start: invalid boot configuration.

    CORS_ALLOWED_ORIGINS: must be explicit in production
    SESSION_COOKIE_SECURE: must be true in production
    SESSION_SECRET: must be at least 32 characters in production

  Set these in the environment (container template, compose
  environment:, or .env) and restart. Nothing else is served
  until they are valid.
========================================================================
```

Fix the named variables where your deployment defines them and restart. Unraid users edit the Community App through its WebUI. CasaOS, Portainer, and TrueNAS users edit the imported Compose-based app or stack; plain Compose uses the `environment:` block or `.env`.

> **3.0 development builds** briefly shipped an interactive setup page at `/setup`, gated by a bootstrap token, that wrote `data/bootstrap.json`. Both are gone. Boot configuration is environment-only, as it was in 2.x. The page could not work on the platforms this is deployed to: every setting arrives as an environment variable there, and env-provided fields were short-circuited back to their current value, so the form silently discarded edits. Any leftover `bootstrap.json` or `setup-token` is ignored and removed on the next successful boot.

Local plain-HTTP example:

```env
APP_ENV=development
SESSION_SECRET=generate-one-stable-64-character-random-hex-value
SESSION_COOKIE_SECURE=false
CORS_ALLOWED_ORIGINS=*
MEDIA_SERVER_TYPE=emby
MEDIA_SERVER_URL=http://localhost:8096
MEDIA_SERVER_API_KEY=your-dedicated-emby-api-key
ENABLE_HLS_TOKEN_VALIDATION=true
```

Jellyfin 10.10+ uses the same two settings and only changes the provider:

```env
MEDIA_SERVER_TYPE=jellyfin
MEDIA_SERVER_URL=http://jellyfin:8096
MEDIA_SERVER_API_KEY=your-dedicated-jellyfin-api-key
```

There is one URL and one key for both providers, because neither was ever
provider-specific; only `MEDIA_SERVER_TYPE` is. It stays explicit, with no
auto-detection: it names which server `MEDIA_SERVER_URL` points at and which
server issued `MEDIA_SERVER_API_KEY`, and changing it requires a restart. Mint
the key on that server, from its own admin dashboard, and keep it dedicated to
Watch Party.

**Renamed in 3.0, with no fallback.** `EMBY_SERVER_URL` and
`JELLYFIN_SERVER_URL` are now `MEDIA_SERVER_URL`; `EMBY_API_KEY` and
`JELLYFIN_API_KEY` are now `MEDIA_SERVER_API_KEY`. The old names are not read
at all, so leaving one in place is a boot error naming its replacement rather
than a silently ignored line. See [the migration guide](docs/Migration-HowTo.md).

Jellyfin playback is HLS-only: HLS stream copy/remux/transcode are supported.
Progressive/direct-file playback, Live TV, Jellyfin SyncPlay, and reuse of GPL
Jellyfin Web code are out of scope. Browser receives opaque local HLS resource
IDs; Jellyfin credentials remain server-side.

**Skip Intro on Jellyfin needs detected intro segments.** Watch Party reads
timings from Jellyfin's `/MediaSegments/{item_id}` API. A segment provider such
as **Intro Skipper** must detect them first; install a compatible plugin version
and let it analyse your library.

**File Transformation** is not required by Watch Party's segment lookup. It is
an optional part of Intro Skipper's enhancements to Jellyfin's own web interface;
see the [plugin's settings](https://github.com/intro-skipper/intro-skipper/wiki/Settings-%E2%80%90-General).

When intro data is absent or unavailable, Skip Intro stays hidden and playback
continues. On Emby the equivalent data comes from the server itself.

Use this only for local development over plain HTTP. Do not expose this permissive configuration to untrusted networks.

Production reverse-proxy example:

```env
APP_ENV=production
BEHIND_PROXY=true
SESSION_SECRET=generate-one-stable-64-character-random-hex-value
SESSION_COOKIE_SECURE=true
CORS_ALLOWED_ORIGINS=https://watchparty.example.com
MEDIA_SERVER_TYPE=emby
MEDIA_SERVER_URL=http://emby:8096
MEDIA_SERVER_API_KEY=your-dedicated-emby-api-key
ENABLE_HLS_TOKEN_VALIDATION=true
TRUSTED_PROXY_CIDRS=172.16.0.0/12
```

If boot configuration becomes invalid, the process stays up and names the failing fields on stderr and in the log. Repair those deployment settings and restart.

### .env

Boot-essential, restart required.

| Variable | Description | Default |
|----------|-------------|---------|
| **Application** | | |
| `WATCH_PARTY_BIND` | IP address to bind to. Supplied container artifacts pin this to `0.0.0.0`. | `0.0.0.0` |
| `WATCH_PARTY_PORT` | Runtime listen port. Supplied container artifacts pin this to `5000`; edit only the published host port. | `5000` |
| `APP_ENV` | `development` or strict startup-validated `production` mode | `development` |
| `APP_PREFIX` | URL prefix for reverse proxy deployments (e.g. `/watchparty`) | (empty) |
| `SESSION_EXPIRY` | Idle session-cookie and administrator-session lifetime in seconds; the default is 24 hours | `86400` |
| **Session cookie** _(new in 2.0.0-beta18)_ | | |
| `SESSION_SECRET` | Stable cookie-signing key, required in production with at least 32 characters. Generate once with `openssl rand -hex 32`; an empty development value uses a new key on each boot. | (generated in development) |
| `SESSION_COOKIE_SECURE` | When `true`, the session cookie carries the `Secure` flag (HTTPS-only). Set `true` in every deployment behind TLS; leave `false` for `http://localhost` dev. | `false` |
| **Socket.IO CORS** _(new in 2.0.0-beta18)_ | | |
| `CORS_ALLOWED_ORIGINS` | Comma-separated origin allowlist for the Socket.IO server (`https://a.example.com,https://b.example.com`). `*` accepts any origin (historical default). Pin to your real origin(s) in production. | `*` |
| `BEHIND_PROXY` | Explicitly declare `true` behind a reverse proxy or `false` for direct access. Production requires a declaration. | (unset) |
| `TRUSTED_PROXY_CIDRS` | Comma-separated proxy source CIDRs allowed to supply forwarding headers; required when `BEHIND_PROXY=true`. Trust only the actual proxy addresses. | (empty) |
| `ENABLE_HLS_TOKEN_VALIDATION` | Restart-required stream-access protection. Production requires `true`. | `true` |
| **Media server** | | |
| `MEDIA_SERVER_TYPE` | Explicit provider: `emby` or `jellyfin`. Not auto-detected; restart to change. | `emby` |
| `MEDIA_SERVER_URL` | URL of the server named by `MEDIA_SERVER_TYPE`, reachable from the backend. | `http://localhost:8096` |
| `MEDIA_SERVER_API_KEY` | Administrative API key issued by that same server. Required in production. | (empty) |

`EMBY_SERVER_URL`, `JELLYFIN_SERVER_URL`, `EMBY_API_KEY` and `JELLYFIN_API_KEY` were retired in 3.0 and are never read; a leftover one fails the boot with the name of its replacement.

`REQUIRE_LOGIN` was previously here. It now lives in the admin panel as a runtime, hot-reloadable setting; see the host-provider authentication model in [Architecture](#architecture) for the full semantics.

### Admin panel

Runtime settings are editable at `/admin`. Most apply immediately. Changing file logging enablement, path, format or rotation size requires restart; log levels apply immediately. See the [project wiki](https://github.com/Oratorian/emby-watchparty/wiki) for a walkthrough.

**Logging**

| Setting | Description | Default |
|---|---|---|
| Log level | Application log verbosity (DEBUG, INFO, WARNING, ERROR) | `INFO` |
| Console log level | Terminal output verbosity | `WARNING` |
| Log to file | Write logs to disk; restart required after changing | `true` |
| Log file | Path to log file; restart required after changing | `logs/emby-watchparty.log` |
| Log format | `rsyslog` or `standard`; restart required after changing | `rsyslog` |
| Max log size (MB) | Rotation threshold; restart required after changing | `10` |

**Security**

| Setting | Description | Default |
|---|---|---|
| Max users per party | 0 = unlimited | `0` |
| HLS token expiry (s) | Token lifetime | `86400` |
| Rate limiting | Enable API rate limiting | `true` |
| Party creation limit | Max per IP | `5 per hour` |
| API rate limit | Max per IP | `1000 per minute` |

**Session**

| Setting | Description | Default |
|---|---|---|
| Static session mode | Auto-create a fixed party on startup | `false` |
| Static session ID | Party code when static mode is enabled | `PARTY` |

**Late join vote** _(new in 2.0)_

| Setting | Description | Default |
|---|---|---|
| Enable late join vote | Require a majority vote to admit users who join mid-playback | `true` |
| Vote timeout (s) | Seconds before the selector tiebreak kicks in | `20` |
| Post-vote cooldown (s) | Delay after a failed vote before another join attempt is allowed (0 disables) | `30` |

## Architecture

### Backend (FastAPI + python-socketio)

- **FastAPI**: async REST API, dependency-injected components, Pydantic schemas for every request/response body (`backend/src/schemas.py`).
- **python-socketio `AsyncServer`** (ASGI mode) mounted under `APP_PREFIX/socket.io`: WebSocket-based real-time sync, hardened with a 128 KiB frame cap and tightened ping timings.
- **httpx**: async media-server requests and HLS proxying; Emby and Jellyfin adapters keep upstream requests and credentials on the backend
- **uvicorn** ASGI worker, bound to `WATCH_PARTY_BIND:WATCH_PARTY_PORT`.
- **HLS.js**-compatible playlists: token-gated (`HLSTokenManager`) short-lived URLs prevent segment scraping.

### Frontend (Vue 3 + TypeScript)

- **Vue 3** SPA authored in **TypeScript**, bundled with **Vite** (base `./` for prefix-agnostic asset resolution).
- **Pinia** stores for auth, party, playback, and socket state; **Vue Router** for `/party/:code`, `/admin`, and landing routes.
- **socket.io-client** for the sync channel, native **fetch** for REST, **hls.js** for adaptive playback.

### Per-user transcode model

Each viewer has a separate media-server playback session. Personal audio, subtitle, quality and media-version changes replace that viewer's stream. Play, pause and seek update the shared party state; a seek while playing coordinates the room through a ready check. Disconnect cleanup releases the departed viewer's active stream when one exists.

### Host-provider authentication

There is no application user database. Any party member can become **host** by authenticating with media-server credentials inside the party (`POST /api/v2/auth/login`). The access token remains server-side in memory. Host disconnect marks the host absent and locks library browsing immediately; the **5-second grace period** allows ownership recovery before final host-left handling. A retained private host grant lets the same browser reclaim ownership while that party and grant remain valid.

- **UNLOCKED** - host present, all playback and library browsing allowed.
- **PLAYING-ONLY** - host absent during playback; the retained token keeps the current video available, including seeks and personal stream changes. Library browsing and selecting a new video are locked.
- **LOCKED** - host gone with no active video; token cleared, party waits for someone to log in as the new host.

### Key components

- **`PartyManager`** - party lifecycle, sid <-> client_id mapping, host state machine, ready-check and late-join vote bookkeeping.
- **Media-server providers** - Emby and Jellyfin adapters for authentication, library operations, playback reporting and HLS resources.
- **`EmbyClient`** - async wrapper for Emby's REST API, used by the Emby provider.
- **`HLSTokenManager`** - mints and validates short-lived per-user HLS URL tokens.
- **`StreamBuilder`** - assembles per-user transcode URLs, honouring the `FORCE_TRANSCODE` admin toggle.
- **`AvatarStore`** - SQLite-backed avatar metadata plus a sibling images directory (both Docker-mountable).

### Deployment

Ships as a **single multi-stage Docker image**: a Node stage runs `npm run build` to produce the Vue bundle, then a Python stage installs backend dependencies and copies the built `static/` into the FastAPI app. One container, one port, one process - uvicorn serves the API, the SPA, and the WebSocket mount under the configurable `APP_PREFIX`.

Party state, standalone admin sessions, and rate-limit buckets are process-local. Run one uvicorn worker unless those stores are moved to shared infrastructure.

## API endpoints

Emby Watch Party 3.0 exposes a FastAPI REST API and a Socket.IO event protocol. The canonical references are:

- **REST / OpenAPI:** `/docs` (Swagger UI), `/redoc` and `/openapi.json` on the running backend. These stay at the hostname root even when `APP_PREFIX` is set.
- **Socket.IO:** [`docs/SOCKET_API.md`](docs/SOCKET_API.md) - every inbound / outbound event, payload shapes, and the multi-step flows.

### REST API (representative endpoints)

Library, media metadata and host-authentication routes live under **`/api/v2`**, the surface used by the bundled web client. The legacy routes were removed in 3.0; the [migration guide](docs/Migration-HowTo.md) maps them to their replacements. Party, HLS, avatar and admin routes have their own prefixes. Examples:

- **`v2`** - `POST /api/v2/auth/login` (media-server login, host-claim), `GET /api/v2/libraries`, `POST /api/v2/items/query`, `GET /api/v2/items/{item_id}/streams`
- **`party`** - `POST /api/party/create`, `POST /api/party/{id}/join`, `GET /api/party/{id}/info`
- **`hls`** - `GET /hls/{item_id}/master.m3u8`, segment and nested-playlist proxy passthrough
- **`quality`** - `GET /api/quality-options`
- **`avatar`** - `POST /api/avatar/upload`, `GET /api/avatar/{avatar_uuid}`
- **`admin`** - `GET/PUT /api/admin/config`, `POST /api/admin/login`
- **`health`** - `GET /api/health` (liveness), `GET /api/ready` (media server reachable and credentials accepted), `GET /api/version`

See `/docs` for the full parameter, response, and auth-scope details.

### WebSocket events (Socket.IO)

Mounted under `${APP_PREFIX}/socket.io`. Events group into these categories:

- **Connection lifecycle** - `connect` / `disconnect` / `connected`, transparent reconnect via stable `client_id`.
- **Party join / leave / vote** - `join_party`, `leave_party`, `user_joined` / `user_left`, plus `join_vote`, `join_vote_pending`, `join_vote_started`, `join_vote_update`, `join_vote_resolved` and `join_rejected`.
- **Host state and visibility** - `host_changed`, `host_left`, `host_reclaimed`, `set_party_hidden` and `party_visibility_changed`.
- **Playback** - `select_video`, `retry_video_selection`, `cancel_video_selection`, `stop_video`, `change_streams` (per-user), `play`, `pause`, `seek`, `video_selection_started`, `video_selection_failed`, `video_selection_cancelled`, `video_selected`, `streams_changed`, `video_stopped`, `video_ended`.
- **Sync coordination** - `stream_ready`, `ready_check_update`, `all_ready`, `force_pause_before_seek`, `heartbeat` + `drift_correction`, `report_progress`.
- **Chat / UI** - `chat_message`, `toggle_library`, `update_avatar` + `members_update`, `sync_state`.
- **Binge-watch / auto-advance** - `set_binge_watch_active`, `binge_watch_state_changed`, `auto_advance_pending`, `auto_advance_cancel(led)`, `auto_advance_fired`, `binge_finished`.
- **Admin / errors** - `party_dissolved`, `rate_limited` and `error`.

Full payloads, auth requirements, and flow diagrams live in [`docs/SOCKET_API.md`](docs/SOCKET_API.md).

## Troubleshooting

Common issues and fixes are catalogued on the wiki: **[Troubleshooting](https://github.com/Oratorian/emby-watchparty/wiki/Troubleshooting)**.

Quick checks before opening an issue:

- **App unreachable.** Confirm the backend is bound on `WATCH_PARTY_BIND`/`WATCH_PARTY_PORT` and that clients can reach it. Behind a reverse proxy, verify `APP_PREFIX` matches the mount path and that WebSocket upgrades are forwarded.
- **Can't browse or play media.** The admin `MEDIA_SERVER_API_KEY` in `.env` must be valid for the server named by `MEDIA_SERVER_TYPE`, and that server (`MEDIA_SERVER_URL`) must be reachable from the backend. A key minted on the other server is a valid key against the wrong server and reads as "credentials rejected". To play, someone in the party has to click **Login to Become Host** and supply their own credentials - nothing plays until a host provider is attached.
- **Playback works, sync doesn't.** Confirm the Socket.IO transport isn't being downgraded or blocked by an intermediate proxy, and that `CORS_ALLOWED_ORIGINS` includes your real origin.
- **Session cookie rejected / kicked out on every restart.** `SESSION_SECRET` must be set to a stable value (`openssl rand -hex 32`). An unset secret regenerates on boot and invalidates every existing cookie; with `--workers >1` each worker signs differently.
- **Logs.** File logging is enabled by default at `logs/emby-watchparty.log`, with application level `INFO`; console output defaults to `WARNING`. Change log levels live in **/admin -> Logging**. File-logging enablement, path, format and rotation changes need a restart.

## Security notes

- **Proxy architecture.** The Emby or Jellyfin server stays on your internal network. The backend fetches and re-serves media resources, so viewers do not need direct access to that server.
- **Credential model.**
  - `MEDIA_SERVER_API_KEY` is the dedicated API key for the configured media server. Keep it and `SESSION_SECRET` out of version control. **Do not commit `.env`.**
  - Host credentials authenticate against the configured Emby or Jellyfin server. The resulting access token stays in server memory and is used for that party's media operations and per-viewer playback sessions.
  - Standalone admin login also keeps its media-server token in an expiring server-side session. The browser cookie contains only an opaque handle.
- **Production mode.** Set `APP_ENV=production`, declare `BEHIND_PROXY`, and supply trusted proxy CIDRs when needed. Startup rejects missing stable session keys, insecure cookies, wildcard CORS, disabled HLS token validation or missing media-server credentials.
- **Session secret and process model.** `SESSION_SECRET` must remain stable across restarts. Run exactly one application process/worker; party state, admin sessions, limiters, background tasks, streams, and HLS tokens are intentionally in-memory and are not shared between workers.
- **HLS URLs.** Since beta18, HLS playlist and segment URLs served to the browser no longer carry the admin `MEDIA_SERVER_API_KEY` as a query parameter. Access is gated by a per-stream HLS token bound to the session cookie; the API key stays server-side.
- **Party codes** are generated with cryptographically secure random tokens.
- **Built-in controls.** HLS token validation is on by default and is a restart-required boot setting, `ENABLE_HLS_TOKEN_VALIDATION`. Bounded per-IP API/party-creation rate limiting and party size limits remain tunable in **/admin -> Security**. Configure `TRUSTED_PROXY_CIDRS` when a reverse proxy supplies client addresses.
- **For internet-facing deployments**, terminate TLS at a reverse proxy (nginx, Caddy, Traefik), set `SESSION_COOKIE_SECURE=true`, and pin `CORS_ALLOWED_ORIGINS` to your real origin(s) instead of `*`.

## License

MIT License - feel free to modify and use as you wish.

## Contributing

Contributions welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for branch conventions, PR flow, and coding guidelines. Issues and feature requests go in GitHub Issues.

Wiki edits are open - if you deploy on hardware or a platform not yet documented, please add your findings.

## Acknowledgments

- Integrates with [Emby Media Server](https://emby.media/) and [Jellyfin](https://jellyfin.org/)
- UI design: **Refined Cyber** by Christian Gillinger
- The community testers on Discord who lived through every beta and kept filing the bug reports that made 2.0 what it is

---

## Educational use notice

This project is intended for educational purposes and private use only. Please use it responsibly and follow the terms and copyright rules that apply to your media server and content.
