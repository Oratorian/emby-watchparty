# Emby Watch Party

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)](https://fastapi.tiangolo.com/)
[![Vue 3](https://img.shields.io/badge/Vue-3-42b883.svg?logo=vue.js&logoColor=white)](https://vuejs.org/)
[![Docker Image](https://img.shields.io/badge/ghcr.io-oratorian%2Femby--watchparty-2496ED.svg?logo=docker&logoColor=white)](https://github.com/Oratorian/emby-watchparty/pkgs/container/emby-watchparty)
[![GitHub release](https://img.shields.io/github/release/Oratorian/emby-watchparty.svg)](https://github.com/Oratorian/emby-watchparty/releases)
[![GitHub stars](https://img.shields.io/github/stars/Oratorian/emby-watchparty.svg)](https://github.com/Oratorian/emby-watchparty/stargazers)
[![Discord](https://img.shields.io/discord/1311999162098782229?logo=discord&logoColor=white&label=discord&color=5865F2)](https://discord.gg/RWUpxq9xsA)

A synchronized watch-party frontend for Emby: watch together in sync while your Emby server stays on your internal network. Any member with Emby credentials can become the room's host; other viewers join as spectators without an account.

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

Thanks to **@stealthydruid** and **@xyxxyxxy** for the bug reports and feature requests on the [Discord support server](https://discord.gg/RWUpxq9xsA) that shaped the late-stage 2.0 betas: APP_PREFIX healthcheck, A-Z library jump bar, image thumbnail sizing, resume from last position, jump-to-timestamp input, and the seek-bar tooltip thinking that got us there.

---

### Discord

https://discord.gg/RWUpxq9xsA

---

## Documentation

- **[Project wiki](https://github.com/Oratorian/emby-watchparty/wiki)** - hardware, deployment, troubleshooting, and FAQ
- **[Migration guide](docs/Migration-HowTo.md)** - upgrade path for 1.x users moving to 2.0
- **[Socket.IO API](docs/SOCKET_API.md)** - developer reference for the Socket.IO event protocol
- **OpenAPI reference** - `GET /docs` (Swagger UI) or `GET /redoc` on a running instance
- **[CHANGELOG.md](CHANGELOG.md)** - per-release details including every fix and the reasoning behind it
- **[SUMMARY-OF-CHANGES.md](SUMMARY-OF-CHANGES.md)** - condensed release-by-release summary of the 2.0 betas
- **[Emby quirks we learned the hard way](docs/Emby%20quirks%20we%20learned%20the%20hard%20way.md)** - Why 2.0 came to be.

## Features

- **Secure proxy architecture**: your Emby server stays on the local network; only the WatchParty app is exposed
- **FastAPI + Vue 3 + TypeScript stack**: async end-to-end, typed OpenAPI docs at `/docs` and `/redoc`, single uvicorn process serves backend + compiled SPA
- **Real-time sync with drift correction**: selector-authoritative play/pause/seek against a party clock, keeping independent streams aligned
- **Late-joiner voting flow**: existing users vote to admit mid-playback joiners; a passing vote restarts on a PTS-aligned segment 0 so everyone lands together
- **Host-provider auth model**: UNLOCKED / PLAYING-ONLY / LOCKED lock states around the Emby-authenticated host, with a grace window for quick refreshes
- **Per-user transcodes**: every viewer gets their own Emby `PlaySessionId`, so audio, subtitles, quality, and version are personal without disrupting the room
- **Multi-version playback**: host-locked picker for items with multiple MediaSources (theatrical vs director's cut, mp4 vs mkv, 1080p vs 4K HDR)
- **Bitrate-granular quality menu**: mirrors Emby's own per-resolution table, with admin-side toggles for exposed resolutions and bitrates
- **Unified subtitles**: text subs via side-channel proxy, image (PGS) subs burned in per-user, both surfaced in one dropdown
- **Resume, jump-to-timestamp, and binge auto-advance**: Continue Watching prompt from Emby `UserData`, absolute-timestamp seek input, and end-of-episode countdown with room-wide Cancel
- **Rooms, chat, and identity**: 5-character party codes, live chat with a mobile slide-over, custom avatars (upload / Gravatar / monsterid fallback) recoverable via 3-word codes
- **Refined Cyber UI**: cyan/magenta/violet palette, glass surfaces, chip/pill controls, animated LIVE badge, iOS-style A-Z library jump bar
- **Reverse-proxy ready**: `APP_PREFIX` wired end-to-end so one Docker image sits behind any subpath (`https://example.com/watchparty/...`)
- **Admin panel with hot-reload**: runtime settings editable from `/admin` as an in-party modal, `.env` reserved for boot-only keys
- **Reload-as-rejoin + healthchecks**: refresh in an active party rejoins via persistent `client_id`; `/api/health` reports liveness and `/api/ready` verifies Emby readiness; rsyslog-style logging with rotation

## Browser compatibility

Emby Watch Party works best with the following browsers:

### Desktop
- **Chrome** - full support (recommended)
- **Edge** - full support (recommended)
- **Firefox** - full support
- **Safari** - full support
- **Brave** - full support

### Mobile
- **Safari (iOS)** - full support with subtitles (recommended for iOS)
- **Chrome (Android)** - full support (recommended for Android)
- **Brave (iOS)** - video playback works, but subtitles do not appear in fullscreen mode
  - **Workaround**: use Safari on iOS if you need subtitle support

### Known issues
- **Brave browser on iOS**: subtitles work in normal view but disappear when entering fullscreen mode. This is a limitation of how Brave handles native video controls on iOS. Safari is recommended for iOS users who need subtitle support.

## Setup

### Prerequisites

- An Emby server (can be on local/internal network only; does **not** need to be exposed to the internet - the app acts as a secure proxy)
- An Emby admin API key (per-user Emby credentials are supplied at runtime via the in-app "Login to Become Host" flow, never in `.env`)
- The app must be reachable by your remote viewers - use a VPN such as Tailscale or Hamachi if you cannot port-forward
- **For Docker installs (recommended):** Docker 20.10+ (and optionally Docker Compose v2)
- **For manual installs:**
  - Python **3.12** or higher (matches the runtime used in the official image)
  - Node.js **20.19+** (or 22.12+) and npm - the Vue 3 frontend is a Vite build that must be produced before FastAPI can serve it

### Manual installation

> Docker (below) is the easier and recommended path - it bundles the frontend build and Python runtime for you. Only use manual installation if you specifically need to run against a local Python environment.

1. **Build the frontend** (Vite emits into `backend/static/`, which FastAPI serves):

   ```bash
   cd frontend
   npm ci
   npm run build
   cd ..
   ```

2. **Install the Python backend dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

3. **Configure your settings.** Copy `.env.example` to `.env` and fill in at least `EMBY_SERVER_URL`, `EMBY_API_KEY`, and `SESSION_SECRET` (generate with `openssl rand -hex 32`):

   ```bash
   cp .env.example .env
   ```

   Only boot-essential settings live in `.env` - see [`.env.example`](.env.example) for the full annotated list (bind/port, `APP_PREFIX`, `SESSION_SECRET`, `SESSION_COOKIE_SECURE`, `CORS_ALLOWED_ORIGINS`, `EMBY_SERVER_URL`, `EMBY_API_KEY`). All other runtime options (logging, rate limits, late-join vote, `FORCE_TRANSCODE`, `REQUIRE_LOGIN`, etc.) are managed live from the Admin Panel at `/admin` and persisted to `config.json`.

4. **Run the application** from the repository root:

   ```bash
   python -m backend.app
   ```

5. Open your browser and navigate to:

   ```
   http://localhost:5000
   ```

   (If you set `APP_PREFIX=/watchparty`, the app is served at `http://localhost:5000/watchparty/` instead.)

### Docker installation

The pre-built multi-arch image is published to GitHub Container Registry:

```bash
docker pull ghcr.io/oratorian/emby-watchparty:latest
```

**Recommended: use the compose example.** Copy [`docker-compose.yml.example`](docker-compose.yml.example) to `docker-compose.yml`, copy `.env.example` to `.env` and fill in your Emby URL + API key, then:

```bash
# One-time: pre-create config.json so Docker does not create it as a
# directory on first `up`. Skip this and the backend will crash trying
# to write its settings.
touch config.json

docker compose up -d
```

The compose file mounts everything correctly out of the box. If you prefer `docker run`, the equivalent invocation is:

```bash
touch config.json

docker run -d \
  --name emby-watchparty \
  -p 5000:5000 \
  --env-file .env \
  -v "$(pwd)/data:/app/data" \
  -v "$(pwd)/images/avatars:/app/images/avatars" \
  -v "$(pwd)/config.json:/app/config.json" \
  -v "$(pwd)/logs:/app/logs" \
  ghcr.io/oratorian/emby-watchparty:latest
```

**Required mounts** (avatars and runtime config will be wiped on container recreation without them):

| Host path | Container path | Purpose |
|-----------|----------------|---------|
| `./data` | `/app/data` | First-run bootstrap config (`bootstrap.json`) and avatar DB (`avatars.db`) |
| `./images/avatars` | `/app/images/avatars` | Uploaded avatar image files |
| `./config.json` | `/app/config.json` | Runtime admin settings (edited via `/admin`) |

**Optional mount:**

| Host path | Container path | Purpose |
|-----------|----------------|---------|
| `./logs` | `/app/logs` | Application logs (only written when `LOG_TO_FILE` is enabled in `/admin`; console-only by default) |

`SESSION_SECRET` is the signing key for the party-bound session cookie. Set it once (`openssl rand -hex 32`) and keep it stable across restarts. When unset, an ephemeral key is generated at boot and every restart invalidates existing sessions. This application is explicitly single-process: do not run multiple Uvicorn workers because parties, sessions, limiters, tasks, and HLS tokens are process-local. Pair production mode with `SESSION_COOKIE_SECURE=true` and explicit `CORS_ALLOWED_ORIGINS`. Full block in [`.env.example`](.env.example).

**Config split (2.0):** boot settings come from process environment, `.env`, or `data/bootstrap.json` and require restart. Runtime options such as `LOG_TO_FILE`, transcoding, and feature toggles remain in `config.json` and the admin panel.

## Usage

### Creating a watch party

The default (`REQUIRE_LOGIN=false`):
1. Click **"Create Party"** on the home page (no login required)
2. Share the party code or URL with your friends
3. Inside the party, click **"Login to Become Host"** with your Emby credentials -- this unlocks the library for everyone in the room. Any party member with an Emby account can do this; spectators never see a login prompt.
4. Browse the library and select a video
5. Everyone in the room will be synchronized

With `REQUIRE_LOGIN=true` (set from the admin panel):
1. Click **"Create Party"** -- you will be prompted for Emby credentials
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

- **Browse library**: use the sidebar to browse your Emby libraries, movies, and TV shows
- **Select video**: click on any video to start watching it with the group
- **Video controls**: any user can play, pause, or seek - all users will sync
- **Audio, subtitles, quality**: each user can pick their own settings independently. If the party is paused, the change is silent; if the party is playing, everyone briefly pauses while the new stream loads so you do not desync
- **Chat**: use the chat box at the bottom to communicate with other viewers
- **Leave**: click the "Leave" button to exit the watch party

## Configuration

Configuration is split into two tiers:

1. **Boot-essential settings** come from environment variables, `.env`, or persistent `data/bootstrap.json` and require restart.
2. **Runtime settings** are editable from the **admin panel** at `/admin` (Emby administrator credentials required) and are hot-reloadable -- no restart needed.

### First-run setup

When boot configuration is invalid, the process remains reachable in restricted setup mode. Normal API, Socket.IO, HLS, admin, and application routes return `503`; liveness returns HTTP `200` with `status: setup_required`, and readiness returns `503` with the same status.

1. Read the one-time bootstrap token from the server console or the mode-`0600` `data/setup-token` recovery file. **Treat this token like a password: never publish it, paste it into a URL, or include it in support logs.** The file is removed after setup succeeds.
2. Open `http://localhost:5000/setup` (or `${APP_PREFIX}/setup`) and enter the token in the form.
3. Choose **Local development** for plain local HTTP with a non-secure cookie, or **Production HTTPS** for a TLS-terminating reverse proxy with a secure cookie and explicit public CORS origin.
4. Validate and save. The server writes `data/bootstrap.json` atomically, disables further setup writes in that process, and requests restart; it never restarts itself from the HTTP request.
5. Restart the service. Valid saved settings start the normal application.

`data/bootstrap.json` contains secrets entered through setup in plaintext with restrictive file permissions where supported. Secrets injected through process environment or `.env` are deliberately not copied into it. Protect the host directory and backups. Docker users must keep `./data:/app/data` mounted; otherwise a missing bootstrap sentinel forces setup mode rather than silently falling back to development defaults.

Boot precedence is exact: **process environment → `.env` → `data/bootstrap.json` → defaults**. Process environment and `.env` are one explicit-operator tier, with process values winning. Setup cannot override an invalid explicit environment value; remove or fix it, then restart. Reading `.env` does not mutate the running process environment.

Local plain-HTTP example:

```env
APP_ENV=development
SESSION_SECRET=generate-one-stable-64-character-random-hex-value
SESSION_COOKIE_SECURE=false
CORS_ALLOWED_ORIGINS=*
EMBY_SERVER_URL=http://localhost:8096
EMBY_API_KEY=your-dedicated-emby-api-key
ENABLE_HLS_TOKEN_VALIDATION=true
```

Use this only for local development over plain HTTP. Do not expose this permissive configuration to untrusted networks.

Production reverse-proxy example:

```env
APP_ENV=production
SESSION_SECRET=generate-one-stable-64-character-random-hex-value
SESSION_COOKIE_SECURE=true
CORS_ALLOWED_ORIGINS=https://watchparty.example.com
EMBY_SERVER_URL=http://emby:8096
EMBY_API_KEY=your-dedicated-emby-api-key
ENABLE_HLS_TOKEN_VALIDATION=true
TRUSTED_PROXY_CIDRS=172.16.0.0/12
```

If saved configuration becomes invalid, missing, or damaged, restart to enter setup mode and use the new token. If an environment override is invalid, repair that deployment setting first. Never send `bootstrap.json` or bootstrap tokens to untrusted parties.

### .env

Boot-essential, restart required.

| Variable | Description | Default |
|----------|-------------|---------|
| **Application** | | |
| `WATCH_PARTY_BIND` | IP address to bind to | `0.0.0.0` |
| `WATCH_PARTY_PORT` | Port to run on | `5000` |
| `APP_ENV` | `development` or strict startup-validated `production` mode | `development` |
| `APP_PREFIX` | URL prefix for reverse proxy deployments (e.g. `/watchparty`) | (empty) |
| `SESSION_EXPIRY` | Session expiry in seconds | `86400` |
| **Session cookie** _(new in 2.0.0-beta18)_ | | |
| `SESSION_SECRET` | Signing key for the party-bound session cookie. Generate ONCE with `openssl rand -hex 32` and leave it. Empty = ephemeral random per boot with a loud warning (every restart kicks users out; multi-worker deploys are non-deterministic). | (generated) |
| `SESSION_COOKIE_SECURE` | When `true`, the session cookie carries the `Secure` flag (HTTPS-only). Set `true` in every deployment behind TLS; leave `false` for `http://localhost` dev. | `false` |
| **Socket.IO CORS** _(new in 2.0.0-beta18)_ | | |
| `CORS_ALLOWED_ORIGINS` | Comma-separated origin allowlist for the Socket.IO server (`https://a.example.com,https://b.example.com`). `*` accepts any origin (historical default). Pin to your real origin(s) in production. | `*` |
| `TRUSTED_PROXY_CIDRS` | Comma-separated proxy CIDRs allowed to supply client-IP forwarding headers. Empty ignores forwarded headers. | (empty) |
| `ENABLE_HLS_TOKEN_VALIDATION` | Restart-required stream-access protection. Production requires `true`. | `true` |
| **Emby server** | | |
| `EMBY_SERVER_URL` | Your Emby server URL | `http://localhost:8096` |
| `EMBY_API_KEY` | Emby API key (server admin key) | (required) |

`REQUIRE_LOGIN` was previously here. It now lives in the admin panel as a runtime, hot-reloadable setting; see the host-provider authentication model in [Architecture](#architecture) for the full semantics.

### Admin panel

Runtime, hot-reloadable. All of the following settings are editable at `/admin`. See the [project wiki](https://github.com/Oratorian/emby-watchparty/wiki) for a walkthrough.

**Logging**

| Setting | Description | Default |
|---|---|---|
| Log level | Application log verbosity (DEBUG, INFO, WARNING, ERROR) | `INFO` |
| Console log level | Terminal output verbosity | `WARNING` |
| Log to file | Write logs to disk | `true` |
| Log file | Path to log file | `logs/emby-watchparty.log` |
| Log format | `rsyslog` or `standard` | `rsyslog` |
| Max log size (MB) | Rotation threshold | `10` |

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
- **httpx**: async HLS proxy - the backend streams `.m3u8`/`.ts`/`.vtt` segments from Emby on the user's behalf so the Emby server never sees the public internet.
- **uvicorn** ASGI worker, bound to `WATCH_PARTY_BIND:WATCH_PARTY_PORT`.
- **HLS.js**-compatible playlists: token-gated (`HLSTokenManager`) short-lived URLs prevent segment scraping.

### Frontend (Vue 3 + TypeScript)

- **Vue 3** SPA authored in **TypeScript**, bundled with **Vite** (base `./` for prefix-agnostic asset resolution).
- **Pinia** stores for auth, party, playback, and socket state; **Vue Router** for `/party/:code`, `/admin`, and landing routes.
- **socket.io-client** for the sync channel, **axios** for REST, **hls.js** for adaptive playback.

### Per-user transcode model

Each viewer gets their own `PlaySessionId` and a fresh Emby transcode session built by `StreamBuilder`. Seeks, quality changes, and disconnects only affect the individual user's stream - the party's shared clock stays authoritative, and Emby's `stop_active_encodings` is called on every disconnect to reap the transcode.

### Host-provider authentication

There is no application user database. Any party member can promote themselves to **host** by authenticating with Emby credentials from inside the party (`POST /api/auth/login`). The resulting `AccessToken` lives **in RAM only** on the `PartyManager` party record and is never persisted or sent to clients. When the host disconnects, a **5-second grace timer** starts; a refresh/reconnect during that window silently reclaims host. If the timer expires, the party transitions through a three-state lock:

- **UNLOCKED** - host present, all playback and library browsing allowed.
- **PLAYING-ONLY** - host gone mid-playback; the in-flight token is retained so viewers can finish the current video, but no new playback or seeks may start.
- **LOCKED** - host gone with no active video; token cleared, party waits for someone to log in as the new host.

### Key components

- **`PartyManager`** - party lifecycle, sid <-> client_id mapping, host state machine, ready-check and late-join vote bookkeeping.
- **`EmbyClient`** - thin async wrapper around Emby's REST API (auth, items, playback reporting, encoding teardown).
- **`HLSTokenManager`** - mints and validates short-lived per-user HLS URL tokens.
- **`StreamBuilder`** - assembles per-user transcode URLs, honouring the `FORCE_TRANSCODE` admin toggle.
- **`AvatarStore`** - SQLite-backed avatar metadata plus a sibling images directory (both Docker-mountable).

### Deployment

Ships as a **single multi-stage Docker image**: a Node stage runs `npm run build` to produce the Vue bundle, then a Python stage installs backend dependencies and copies the built `static/` into the FastAPI app. One container, one port, one process - uvicorn serves the API, the SPA, and the WebSocket mount under the configurable `APP_PREFIX`.

Party state, standalone admin sessions, and rate-limit buckets are process-local. Run one uvicorn worker unless those stores are moved to shared infrastructure.

## API endpoints

Emby Watch Party 2.0 ships a FastAPI backend (REST + OpenAPI) and a Socket.IO real-time surface. Rather than duplicate the full spec here, the canonical references are:

- **REST / OpenAPI:** interactive docs at `/docs` (Swagger UI) and `/redoc` when the backend is running.
- **Socket.IO:** [`docs/SOCKET_API.md`](docs/SOCKET_API.md) - every inbound / outbound event, payload shapes, and the multi-step flows.

### REST API (representative endpoints)

The FastAPI app is composed of nine routers under `backend/src/routers/`. A small sample:

- **`auth`** - `POST /api/auth/login` (Emby login, host-claim), `POST /api/auth/logout`
- **`party`** - `POST /api/party/create`, `POST /api/party/{id}/join`, `GET /api/party/{id}/info`
- **`library`** - `GET /api/libraries`, `GET /api/items?parentId=...`, `GET /api/item/{item_id}`
- **`media`** - `GET /api/media/{item_id}/streams`, `GET /api/media/{item_id}/versions`
- **`hls`** - `GET /api/hls/{session}/master.m3u8`, segment + subtitle proxy passthrough
- **`quality`** - `GET /api/quality/profiles`, `GET /api/quality/default`
- **`avatar`** - `POST /api/avatar/upload`, `GET /api/avatar/{uuid}`
- **`admin`** - `GET/PUT /api/admin/config`, `POST /api/admin/party/{id}/dissolve`
- **`health`** - `GET /api/health` (liveness), `GET /api/ready` (Emby readiness), `GET /api/version`

See `/docs` for the full parameter, response, and auth-scope details.

### WebSocket events (Socket.IO)

Mounted under `${APP_PREFIX}/socket.io`. Events group into these categories:

- **Connection lifecycle** - `connect` / `disconnect` / `connected`, transparent reconnect via stable `client_id`.
- **Party join / leave / vote** - `join_party`, `leave_party`, `user_joined` / `user_left`, plus the late-joiner vote (`join_vote`, `join_vote_started`, `join_vote_update`, `join_vote_resolved`, `join_rejected`).
- **Host state** - `host_changed`, `host_left`, `host_reclaimed`, three-state lock (UNLOCKED / PLAYING-ONLY / LOCKED).
- **Playback** - `select_video`, `stop_video`, `change_streams` (per-user), `play`, `pause`, `seek`, `video_selected`, `streams_changed`, `video_stopped`, `video_ended`.
- **Sync coordination** - `stream_ready`, `ready_check_update`, `all_ready`, `force_pause_before_seek`, `heartbeat` + `drift_correction`, `report_progress`.
- **Chat / UI** - `chat_message`, `toggle_library`, `update_avatar` + `members_update`, `sync_state`.
- **Binge-watch / auto-advance** - `set_binge_watch_active`, `binge_watch_state_changed`, `auto_advance_pending`, `auto_advance_cancel(led)`, `auto_advance_fired`, `binge_finished`.
- **Admin / errors** - `party_dissolved`, `error`.

Full payloads, auth requirements, and flow diagrams live in [`docs/SOCKET_API.md`](docs/SOCKET_API.md).

## Troubleshooting

Common issues and fixes are catalogued on the wiki: **[Troubleshooting](https://github.com/Oratorian/emby-watchparty/wiki/Troubleshooting)**.

Quick checks before opening an issue:

- **App unreachable.** Confirm the backend is bound on `WATCH_PARTY_BIND`/`WATCH_PARTY_PORT` and that clients can reach it. Behind a reverse proxy, verify `APP_PREFIX` matches the mount path and that WebSocket upgrades are forwarded.
- **Can't browse or play media.** The admin `EMBY_API_KEY` in `.env` must be valid, and the Emby server (`EMBY_SERVER_URL`) must be reachable from the backend. To play, someone in the party has to click **Login to Become Host** and supply their own Emby credentials - nothing plays until a host provider is attached.
- **Playback works, sync doesn't.** Confirm the Socket.IO transport isn't being downgraded or blocked by an intermediate proxy, and that `CORS_ALLOWED_ORIGINS` includes your real origin.
- **Session cookie rejected / kicked out on every restart.** `SESSION_SECRET` must be set to a stable value (`openssl rand -hex 32`). An unset secret regenerates on boot and invalidates every existing cookie; with `--workers >1` each worker signs differently.
- **Logs.** Logging goes to stdout by default. File logging is opt-in from **/admin -> Logging**; the log path shown there is where to look once enabled.

## Security notes

- **Proxy architecture.** The Emby server stays on your internal network. All HLS segments and playlists are pulled by the backend and re-served to clients, so browsers never talk to Emby directly.
- **Credential model.**
  - `.env` holds only the admin `EMBY_API_KEY`, used for library browsing and administrative Emby calls. **Do not commit `.env`.**
  - Per-user Emby credentials are never persisted. Any party member can click **Login to Become Host** in-app and authenticate against Emby; the resulting AccessToken lives in memory as that party's *host provider* and is used to open per-user transcode sessions. Tokens are discarded when the host provider changes or the party ends.
  - Standalone admin login also keeps its Emby token server-side in a bounded, expiring in-memory session. The browser cookie contains only an opaque handle.
- **Production mode.** Set `APP_ENV=production`; startup then rejects missing stable session keys, insecure cookies, wildcard CORS, disabled HLS token validation, or missing Emby credentials.
- **Session secret and process model.** `SESSION_SECRET` must remain stable across restarts. Run exactly one application process/worker; party state, admin sessions, limiters, background tasks, streams, and HLS tokens are intentionally in-memory and are not shared between workers.
- **HLS URLs.** Since beta18, HLS playlist and segment URLs served to the browser no longer carry the admin `EMBY_API_KEY` as a query parameter. Access is gated by a per-stream HLS token bound to the session cookie; the API key stays server-side.
- **Party codes** are generated with cryptographically secure random tokens.
- **Built-in controls.** HLS token validation is on by default and is a restart-required boot setting configured through first-run setup or `ENABLE_HLS_TOKEN_VALIDATION` in `.env`. Bounded per-IP API/party-creation rate limiting and party size limits remain tunable in **/admin -> Security**. Configure `TRUSTED_PROXY_CIDRS` when a reverse proxy supplies client addresses.
- **For internet-facing deployments**, terminate TLS at a reverse proxy (nginx, Caddy, Traefik), set `SESSION_COOKIE_SECURE=true`, and pin `CORS_ALLOWED_ORIGINS` to your real origin(s) instead of `*`.

## License

MIT License - feel free to modify and use as you wish.

## Contributing

Contributions welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for branch conventions, PR flow, and coding guidelines. Issues and feature requests go in GitHub Issues.

Wiki edits are open - if you deploy on hardware or a platform not yet documented, please add your findings.

## Acknowledgments

- Integrates with [Emby Media Server](https://emby.media/)
- UI design: **Refined Cyber** by Christian Gillinger
- The community testers on Discord who lived through every beta and kept filing the bug reports that made 2.0 what it is

---

## Educational use notice

This project is intended for educational purposes and private use only. Please ensure you use this responsibly and in compliance with your Emby server's terms of service and applicable copyright laws.
