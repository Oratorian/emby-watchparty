# Emby Watch Party

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Flask](https://img.shields.io/badge/flask-3.1.3-green.svg)](https://flask.palletsprojects.com/)
[![GitHub release](https://img.shields.io/github/release/Oratorian/emby-watchparty.svg)](https://github.com/Oratorian/emby-watchparty/releases)
[![GitHub stars](https://img.shields.io/github/stars/Oratorian/emby-watchparty.svg)](https://github.com/Oratorian/emby-watchparty/stargazers)

A synchronized watch party application for Emby media servers. Watch videos together with friends in real-time, no matter where you are — no Emby account required for your guests.

---

## Table of contents

- [Support development](#support-development)
- [Special Thanks](#-special-thanks)
- [Discord](#discord-for-more-personal-support)
- [Documentation](#documentation)
  - [Wiki](#wiki) — hardware, deployment, troubleshooting, FAQ
  - [Emby quirks we learned the hard way](#technical-deep-dive-emby-quirks)
  - [Changelog](#changelog)
- [Features](#features)
- [Browser compatibility](#browser-compatibility)
- [Setup](#setup)
  - [Prerequisites](#prerequisites)
  - [Option 1: Manual installation](#option-1-manual-installation)
  - [Option 2: Docker installation](#option-2-docker-installation)
- [Usage](#usage)
  - [Creating a watch party](#creating-a-watch-party)
  - [Joining a watch party](#joining-a-watch-party)
  - [In-party controls](#in-party-controls)
- [Configuration](#configuration)
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

If Emby WatchParty has saved you from the hell of trying to coordinate "3, 2, 1, play" over Discord, consider buying me a coffee:

☕ **[ko-fi.com/jedziah](https://ko-fi.com/jedziah)**

Every tip helps fund the hardware and the late nights reverse-engineering Emby's HLS pipeline.

---

### 🎉 Special Thanks

Special thanks to **[QuackMasterDan](https://emby.media/community/index.php?/profile/1658172-quackmasterdan/)** for his dedication in testing and providing valuable feedback throughout development.

Thanks to **[wlowen](https://github.com/wlowen)** and **[JeslynMcKenzie](https://github.com/JeslynMcKenzie)** for testing, detailed bug reports, and providing mediainfo that helped track down the HEVC transcoding and HLS seeking issues.

---

### Discord for more personal support

https://discord.gg/RWUpxq9xsA

---

## Documentation

### Wiki

The [project wiki](https://github.com/Oratorian/emby-watchparty/wiki) has everything you need for deployment and operations:

- **[Home](https://github.com/Oratorian/emby-watchparty/wiki/Home)** — start here
- **[Hardware Requirements](https://github.com/Oratorian/emby-watchparty/wiki/Hardware-Requirements)** — how many users your hardware can actually handle, with real measurements from stress tests
- **Deployment guides:**
  - **[Docker Compose](https://github.com/Oratorian/emby-watchparty/wiki/Deployment-Docker-Compose)** — full stack including GPU passthrough per vendor (Intel QSV, NVIDIA NVENC, AMD VAAPI)
  - **[Unraid](https://github.com/Oratorian/emby-watchparty/wiki/Deployment-Unraid)** — Extra Parameters, render group GID, Nvidia Driver plugin
  - **[TrueNAS SCALE](https://github.com/Oratorian/emby-watchparty/wiki/Deployment-TrueNAS-SCALE)** — K8s and Fangtooth-Docker app configurations
  - **[TrueNAS CORE](https://github.com/Oratorian/emby-watchparty/wiki/Deployment-TrueNAS-CORE)** — honest about FreeBSD's no-QSV/NVENC limitation and your options
- **[Troubleshooting](https://github.com/Oratorian/emby-watchparty/wiki/Troubleshooting)** — seeking, CPU usage, network, container, and Emby-side issues by symptom
- **[FAQ](https://github.com/Oratorian/emby-watchparty/wiki/FAQ)** — recurring questions

### Technical deep dive: Emby quirks

[Emby quirks we learned the hard way](docs/Emby%20quirks%20we%20learned%20the%20hard%20way.md) documents the undocumented Emby server behaviors discovered through reverse-engineering the HLS API and countless hours reading raw ffmpeg commands in server logs. Essential reading if you're building a third-party HLS client against Emby, or just curious why this app works the way it does.

The ten quirks covered:

1. `VideoCodec=h264` does **not** force a transcode (Emby interprets it as "client accepts h264" and stream-copies)
2. `EnableDirectPlay=false` and `EnableDirectStream=false` on PlaybackInfo are **advisory only** — the HLS endpoint makes its own decision
3. `EnableAutoStreamCopy=false` is the actual flag that forces a real re-encode — used throughout this app
4. Emby's `PlaybackInfo` does not expose **peak bitrate** — only average, making peak-based logic impossible
5. `AutoOpenLiveStream=true` pre-starts ffmpeg so the first segment is ready faster
6. Emby's own web client **restarts the entire pipeline on seek** — a trick HLS.js can't replicate
7. HLS playlist segment durations **lie** when stream-copying — they're uniform on paper, irregular in reality
8. The "triple failsafe" (`MaxStreamingBitrate` + `h264-profile` + `h264-level` + `TranscodeReasons`) does **not** prevent stream-copy
9. Concurrent seeks on a shared `PlaySessionId` cause **ffmpeg race conditions** — the reason 2.0 moved to per-user transcodes
10. The CPU cost of forced re-encoding is real on software, near-zero with Intel QSV / NVENC / VAAPI — with measured numbers on a 9900K + UHD 630

### Changelog

[CHANGELOG.md](CHANGELOG.md) — per-release details including every fix and the reasoning behind it.

## Features

- **Secure proxy architecture**: Emby server stays on your local network, never exposed to the internet
- **HLS streaming**: HTTP Live Streaming with forced re-encoding for reliable seek behavior (see the quirks doc for why this matters)
- **Real-time sync**: play, pause, and seek events propagate to every viewer instantly
- **Library browsing**: browse your entire Emby library and pick videos to watch together
- **Skip Intro button**: overlay button that appears during intro segments (uses Emby's chapter/intro data)
- **Autoplay / binge mode**: optional auto-queue of the next episode when the current one ends, with a countdown and cancel option
- **Quality presets**: pick from 360p up to 1080p-high (10 Mbps), or let the app decide
- **Subtitle & audio support**: native HLS manifest subtitles (VTT), automatic image-subtitle burn-in (PGS/VobSub), per-party audio track selection
- **Room system**: 5-character party codes, no accounts needed for guests
- **Live chat**: built-in chat alongside the video
- **Random usernames**: 554,400+ auto-generated usernames for users who don't set one
- **Multiple users**: unlimited concurrent viewers per party (bounded by your Emby server's hardware — see the wiki)
- **Static session mode**: optional single-party-always-open deployment for private groups
- **Professional logging**: rsyslog-style logging with rotation

## Browser compatibility

### Desktop
- ✅ **Chrome / Edge / Brave** — full support (recommended)
- ✅ **Firefox** — full support
- ✅ **Safari** — full support

### Mobile
- ✅ **Safari (iOS)** — full support including subtitles (recommended for iOS)
- ✅ **Chrome (Android)** — full support (recommended for Android)
- ⚠️ **Brave (iOS)** — video plays, but subtitles don't show in fullscreen. Use Safari on iOS if you need subtitles.

## Setup

### Prerequisites

- Python 3.8 or higher
- An Emby server (stays on your local/internal network)
- **Emby API key AND username/password** — both are required. The API key is used for admin API calls (library browsing, item lookup), and the username/password are needed to get a stream access token (Emby only serves HLS to authenticated user sessions).
- The Flask app must be reachable by your guests. If you can't port-forward, use Tailscale, ZeroTier, or a similar overlay VPN.
- **Emby Premiere** is required on the Emby side if you want hardware-accelerated transcoding (QSV, NVENC, VAAPI). Without it, Emby transcodes in software only.

### Option 1: Manual installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Configure your settings — copy `.env.example` to `.env`:
```bash
cp .env.example .env
```

3. Edit `.env`:
```env
# Emby Server Configuration
EMBY_SERVER_URL=http://your-emby-server:8096
EMBY_API_KEY=your-api-key-here
EMBY_USERNAME=your-emby-username
EMBY_PASSWORD=your-emby-password

# Application Configuration
WATCH_PARTY_BIND=0.0.0.0
WATCH_PARTY_PORT=5000
```

4. Run:
```bash
python run_production.py
```

5. Open your browser at `http://localhost:5000` (or your server's IP).

### Option 2: Docker installation

Pull from GitHub Container Registry:
```bash
docker pull ghcr.io/oratorian/emby-watchparty:latest
```

Run with a `.env` file:
```bash
docker run -d \
  --name emby-watchparty \
  -p 5000:5000 \
  --env-file .env \
  ghcr.io/oratorian/emby-watchparty:latest
```

Or with inline environment variables:
```bash
docker run -d \
  --name emby-watchparty \
  -p 5000:5000 \
  -e EMBY_SERVER_URL=http://your-emby-server:8096 \
  -e EMBY_API_KEY=your-api-key \
  -e EMBY_USERNAME=your-emby-username \
  -e EMBY_PASSWORD=your-emby-password \
  -e LOG_TO_FILE=false \
  ghcr.io/oratorian/emby-watchparty:latest
```

**Note:** for Docker deployments, set `LOG_TO_FILE=false` so logs go to stdout (readable via `docker logs`).

For Unraid, TrueNAS SCALE, and full-stack Docker Compose setups (including GPU passthrough for hardware-accelerated transcoding), see the **[deployment guides in the wiki](https://github.com/Oratorian/emby-watchparty/wiki)**.

## Usage

### Creating a watch party

1. Click **"Create Party"** on the home page
2. Share the 5-character party code with your friends
3. Browse the Emby library and pick a video
4. Everyone stays synchronized automatically

### Joining a watch party

1. Click **"Join Watch Party"** on the home page
2. Enter the party code
3. Enter a username (or leave blank for a random one)
4. Start watching together

### In-party controls

- **Browse Library**: sidebar browser for your Emby libraries, movies, and TV shows
- **Select Video**: click any video to start it for the whole party
- **Video Controls**: any user can play, pause, or seek — sync happens automatically
- **Skip Intro**: when the overlay appears, click to skip the intro segment
- **Autoplay toggle**: enable "Autoplay: ON" to queue the next episode automatically when the current one ends (with a cancel option during the countdown)
- **Quality selector**: pick a quality preset if automatic selection isn't what you want
- **Chat**: bottom chat box for talking to other viewers
- **Leave**: exit the party

## Configuration

All configuration is via `.env`. Copy `.env.example` and customize:

| Variable | Description | Default |
|----------|-------------|---------|
| **Application** | | |
| `WATCH_PARTY_BIND` | IP to bind to | `0.0.0.0` |
| `WATCH_PARTY_PORT` | Port to listen on | `5000` |
| `APP_PREFIX` | URL prefix for reverse proxy deployments (e.g. `/watchparty`) | (empty) |
| `REQUIRE_LOGIN` | Require Emby login to access the web UI | `false` |
| `SESSION_EXPIRY` | Session expiry in seconds | `86400` |
| `STATIC_SESSION_ENABLED` | Keep a single persistent party alive across restarts | `false` |
| `STATIC_SESSION_ID` | Fixed party ID when `STATIC_SESSION_ENABLED=true` | `PARTY` |
| **Emby Server** | | |
| `EMBY_SERVER_URL` | Your Emby server URL | `http://localhost:8096` |
| `EMBY_API_KEY` | Emby API key | (required) |
| `EMBY_USERNAME` | Emby username | (required) |
| `EMBY_PASSWORD` | Emby password | (required) |
| **Logging** | | |
| `LOG_LEVEL` | DEBUG, INFO, WARNING, ERROR | `INFO` |
| `LOG_TO_FILE` | Enable file logging | `true` |
| `LOG_FILE` | Path to log file | `logs/emby-watchparty.log` |
| `CONSOLE_LOG_LEVEL` | Console log level | `WARNING` |
| `LOG_MAX_SIZE` | Max log file size in MB | `10` |
| **Security** | | |
| `MAX_USERS_PER_PARTY` | Max users per party (0 = unlimited) | `0` |
| `ENABLE_HLS_TOKEN_VALIDATION` | Validate HLS stream tokens | `true` |
| `HLS_TOKEN_EXPIRY` | HLS token expiry in seconds | `86400` |
| `ENABLE_RATE_LIMITING` | Enable API rate limiting | `true` |
| `RATE_LIMIT_PARTY_CREATION` | Max party creations per IP per hour | `5` |
| `RATE_LIMIT_API_CALLS` | Max API calls per IP per minute | `1000` |

## Architecture

### Backend (Flask + SocketIO)

- **Flask**: web server and REST API
- **Flask-SocketIO**: WebSocket-based real-time sync between party members
- **EmbyClient**: custom Emby API wrapper that handles authentication, playback info, HLS stream URL construction, and playback progress reporting
- **HLS streaming**: every stream is **force-transcoded** (not stream-copied) via `EnableAutoStreamCopy=false` to guarantee reliable seeking with HLS.js. See the [quirks doc](docs/Emby%20quirks%20we%20learned%20the%20hard%20way.md) for the full backstory.

### Frontend

- **Vanilla JavaScript**: no frameworks, no build step
- **Socket.IO client**: real-time bidirectional sync
- **HLS.js**: adaptive-bitrate HLS player with buffering and error recovery
- **HTML5 Video**: native player with custom overlay controls

### Key concepts

**Watch party rooms** — each room tracks connected users, the selected video, and playback state (playing/paused, current time, last update timestamp).

**Synchronization** — play/pause/seek events are broadcast to all users in the room via WebSocket. The server authoritatively tracks party clock state; clients reconcile their local `video.currentTime` against the server's projection.

**Transcoding** — the Emby server does all video work. WatchParty just proxies HLS segments and tells Emby exactly how to transcode (quality, subtitles, audio track). Forced re-encoding is required for HLS.js seek reliability and is non-negotiable on this branch.

**Authentication** — WatchParty authenticates with Emby using the configured username/password to obtain an AccessToken, then uses that token for HLS streaming. The API key is used separately for metadata calls. All guest traffic is proxied through the Flask app so your Emby server never sees guest IPs.

## API endpoints

### REST API

- `GET /` — home page
- `GET /party/<party_id>` — watch party room page
- `GET /api/libraries` — list media libraries
- `GET /api/items?parentId=<id>&type=<type>&recursive=<bool>` — list items in a library
- `GET /api/item/<item_id>` — item details
- `GET /api/stream/<item_id>` — get a video stream URL for a party
- `POST /api/party/create` — create a new watch party
- `GET /api/party/<party_id>/info` — party state

### WebSocket events

**Client → Server:**
- `join_party` — join a room
- `leave_party` — leave a room
- `select_video` — pick a video for the party
- `play` / `pause` / `seek` — playback control
- `change_quality` — switch quality preset
- `change_audio` / `change_subtitle` — switch tracks (party-wide in 1.x)
- `chat_message` — send chat
- `autoplay_toggle` — toggle binge mode

**Server → Client:**
- `connected` — connection established
- `user_joined` / `user_left` — room membership change
- `sync_state` — playback state sync (authoritative)
- `video_selected` — a new video started
- `play` / `pause` / `seek` — control events from other users
- `chat_message` — chat broadcast
- `intro_data` — skip-intro chapter/timestamp info
- `autoplay_countdown` — next-episode autoplay UI
- `error` — error with context

## Troubleshooting

See the **[Troubleshooting wiki page](https://github.com/Oratorian/emby-watchparty/wiki/Troubleshooting)** for detailed diagnosis of seeking, CPU usage, networking, and configuration issues.

Quick checks:

**Videos won't play**
- Check `logs/emby-watchparty.log` for authentication or proxy errors
- Verify `EMBY_SERVER_URL`, `EMBY_API_KEY`, `EMBY_USERNAME`, `EMBY_PASSWORD` are correct
- Confirm the Emby user account has library access permissions
- Verify the Flask app is reachable from guest browsers

**Seeking is broken, jumps to wrong scenes, or 404s on segments**
- Update to v1.6.3 or later — the `EnableAutoStreamCopy=false` fix is required

**CPU at 100% with a single user**
- Enable hardware acceleration in Emby (Settings → Transcoding → Hardware acceleration) and verify the container has GPU access. See the [wiki hardware guide](https://github.com/Oratorian/emby-watchparty/wiki/Hardware-Requirements).

**Sync drifts or one user keeps buffering**
- Check that user's network speed and device CPU usage
- Try refreshing the page
- Confirm WebSocket traffic isn't being dropped by a firewall or reverse proxy

## Security notes

- **Proxy architecture**: Emby stays on your local network. Only the Flask app is reachable by guests.
- Credentials live in `.env` — **do not commit this to public repos**.
- Party codes are generated using cryptographically secure random tokens.
- HLS tokens (optional) prevent direct stream URL sharing outside the party.
- AccessTokens are obtained at runtime and not stored persistently.
- Built-in security features:
  - HLS token validation (prevents direct stream access bypass)
  - Rate limiting on API endpoints and party creation
  - Configurable per-party user limits
- For production, add:
  - HTTPS via reverse proxy (Caddy, Nginx, Traefik)
  - A VPN or overlay network if guests aren't on the public internet

## License

MIT License — feel free to modify and use as you wish.

## Contributing

Contributions welcome. Fork, branch, PR against `dev`. Issues and feature requests go in GitHub Issues.

Wiki edits are open — if you deploy on hardware or a platform not yet documented, please add your findings.

## Acknowledgments

- Built on Flask, Flask-SocketIO, and HLS.js
- Integrates with [Emby Media Server](https://emby.media/)
- Inspired by various watch-party applications that didn't quite do what we needed

---

## Educational use notice

This project is intended for educational purposes and private use only. Please ensure you use this responsibly and in compliance with your Emby server's terms of service and applicable copyright laws.
