# Emby Watch Party

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Flask](https://img.shields.io/badge/flask-3.1.3-green.svg)](https://flask.palletsprojects.com/)
[![GitHub release](https://img.shields.io/github/release/Oratorian/emby-watchparty.svg)](https://github.com/Oratorian/emby-watchparty/releases)
[![GitHub stars](https://img.shields.io/github/stars/Oratorian/emby-watchparty.svg)](https://github.com/Oratorian/emby-watchparty/stargazers)

A synchronized watch party application for Emby media servers. Watch videos together with friends in real-time, no matter where you are!

---

### 🎉 Special Thanks

Special thanks to **[QuackMasterDan](https://emby.media/community/index.php?/profile/1658172-quackmasterdan/)** for his dedication in testing and providing valuable feedback throughout development!

Thanks to **[wlowen](https://github.com/wlowen)** and **[JeslynMcKenzie](https://github.com/JeslynMcKenzie)** for testing, detailed bug reports, and providing mediainfo that helped track down the HEVC transcoding issues!

Thanks to **@stealthydruid** and **@xyxxyxxy** for the bug reports and feature requests on the [Discord support server](https://discord.gg/RWUpxq9xsA) that shaped the late-stage 2.0 betas -- APP_PREFIX healthcheck, A-Z library jump bar, image thumbnail sizing, resume from last position, jump-to-timestamp input, and the seek-bar tooltip thinking that got us there.

---

### Discord for more personal support
https://discord.gg/RWUpxq9xsA

---

## Features

- **Secure Proxy Architecture**: Emby server stays on your local network - never exposed to the internet
- **HLS Streaming**: High-quality HTTP Live Streaming with adaptive bitrate and buffering
- **Real-time synchronization**: Watch videos together with automatic play/pause/seek synchronization
- **Library browsing**: Browse your entire Emby library and select videos to watch
- **Subtitle & Audio Support**: Automatic detection of default tracks with burned-in subtitle support
- **Room system**: Create private watch party rooms with simple 5-character codes
- **Live chat**: Chat with other viewers while watching
- **Random usernames**: Auto-generated usernames if not provided (554,400+ combinations)
- **Multiple users**: Support for unlimited concurrent viewers in a room
- **Professional logging**: rsyslog-style logging with automatic rotation
- **Responsive UI**: Modern, clean interface that works on desktop and mobile

## Browser Compatibility

Emby Watch Party works best with the following browsers:

### Desktop
- ✅ **Chrome** - Full support (recommended)
- ✅ **Edge** - Full support (recommended)
- ✅ **Firefox** - Full support
- ✅ **Safari** - Full support
- ✅ **Brave** - Full support

### Mobile
- ✅ **Safari (iOS)** - Full support with subtitles (recommended for iOS)
- ✅ **Chrome (Android)** - Full support (recommended for Android)
- ⚠️ **Brave (iOS)** - Video playback works, but subtitles do not appear in fullscreen mode
  - **Workaround**: Use Safari on iOS if you need subtitle support

### Known Issues
- **Brave Browser on iOS**: Subtitles work in normal view but disappear when entering fullscreen mode. This is a limitation of how Brave handles native video controls on iOS. Safari is recommended for iOS users who need subtitle support.

## Setup

### Prerequisites

- Python 3.8 or higher
- An Emby server (can be on local/internal network only)
- Emby user account credentials (username and password)
- Flask app must be accessible to remote users - use VPNs like Tailscale or Hamachi if port forwarding is not possible
- **Note:** Emby server does NOT need to be exposed to the internet - the Flask app acts as a secure proxy

### Option 1: Manual Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Configure your settings:

Copy `.env.example` to `.env` and edit with your settings:
```bash
cp .env.example .env
```

Edit `.env` with your Emby server credentials:
```env
# Emby Server Configuration
# Only the admin server API key is needed. Per-user authentication
# happens at runtime via the in-app "Login to Become Host" flow.
EMBY_SERVER_URL=http://your-emby-server:8096
EMBY_API_KEY=your-api-key-here

# Application Configuration
WATCH_PARTY_BIND=0.0.0.0
WATCH_PARTY_PORT=5000
```

3. Run the application:

```bash
python run_production.py
```

4. Open your browser and navigate to:
```
http://localhost:5000
```

### Option 2: Docker Installation

Pull the image from GitHub Container Registry:
```bash
docker pull ghcr.io/oratorian/emby-watchparty:latest
```

Run with your `.env` file:
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
  -e LOG_TO_FILE=false \
  -v /your/path/data:/app/data \
  -v /your/path/images:/app/images \
  ghcr.io/oratorian/emby-watchparty:latest
```

The two volume mounts keep the avatar database (`/app/data/avatars.db`)
and uploaded avatar files (`/app/images/avatars/`) outside the
container so they survive image updates.

**Note:** For Docker deployments, set `LOG_TO_FILE=false` to output logs to stdout only.

## Usage

### Creating a Watch Party

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

### Joining a Watch Party

1. Click **"Join Watch Party"** on the home page (or open a shared URL)
2. Enter the party code if needed
3. Enter your username
4. Start watching together!

If you join **before** a video has been selected, you land directly in
the party. If you join **while a video is already playing**, the
existing users will see a vote modal asking whether to restart the
video from the beginning so you can join in sync. See the
[project wiki](https://github.com/Oratorian/emby-watchparty/wiki)
for full details of the late-joiner vote flow.

### Controls

- **Browse Library**: Use the sidebar to browse your Emby libraries, movies, and TV shows
- **Select Video**: Click on any video to start watching it with the group
- **Video Controls**: Any user can play, pause, or seek - all users will sync
- **Audio / Quality / Subtitles**: Each user can pick their own settings
  independently. If the party is paused, the change is silent; if the
  party is playing, everyone briefly pauses while the new stream loads
  so you do not desync
- **Chat**: Use the chat box at the bottom to communicate with other viewers
- **Leave**: Click the "Leave" button to exit the watch party

### Documentation

- **[Project wiki](https://github.com/Oratorian/emby-watchparty/wiki)** -
  End-user docs covering the full party flow, late-joiner vote,
  per-user streams, and the admin panel
- **[Socket.IO API](docs/SOCKET_API.md)** - Developer reference for
  the Socket.IO event protocol
- **REST API** - `GET /docs` or `GET /redoc` on a running instance for
  the auto-generated OpenAPI documentation

## Configuration

Configuration is split into two tiers:

1. **Boot-essential settings** live in `.env` and require a server
   restart to change. Copy `.env.example` to `.env` and set these
   before starting the service.
2. **Runtime settings** are editable from the **admin panel** at
   `/admin` (Emby administrator credentials required) and are
   hot-reloadable -- no restart needed.

### `.env` (boot-essential, restart required)

| Variable | Description | Default |
|----------|-------------|---------|
| **Application** | | |
| `WATCH_PARTY_BIND` | IP address to bind to | `0.0.0.0` |
| `WATCH_PARTY_PORT` | Port to run on | `5000` |
| `APP_PREFIX` | URL prefix for reverse proxy deployments (e.g. `/watchparty`) | (empty) |
| `SESSION_EXPIRY` | Session expiry in seconds | `86400` |
| **Emby Server** | | |
| `EMBY_SERVER_URL` | Your Emby server URL | `http://localhost:8096` |
| `EMBY_API_KEY` | Emby API key (server admin key) | (required) |

`REQUIRE_LOGIN` was previously here. It now lives in the admin panel as
a runtime, hot-reloadable setting; see the **Authentication & Library
Locking** section above for the full semantics.

### Admin panel (runtime, hot-reloadable)

All of the following settings are editable at `/admin`. See the
[project wiki](https://github.com/Oratorian/emby-watchparty/wiki) for a walkthrough.

**Logging**

| Setting | Description | Default |
|---|---|---|
| Log Level | Application log verbosity (DEBUG, INFO, WARNING, ERROR) | `INFO` |
| Console Log Level | Terminal output verbosity | `WARNING` |
| Log to File | Write logs to disk | `true` |
| Log File | Path to log file | `logs/emby-watchparty.log` |
| Log Format | `rsyslog` or `standard` | `rsyslog` |
| Max Log Size (MB) | Rotation threshold | `10` |

**Security**

| Setting | Description | Default |
|---|---|---|
| Max Users per Party | 0 = unlimited | `0` |
| HLS Token Validation | Prevent direct stream access bypass | `true` |
| HLS Token Expiry (s) | Token lifetime | `86400` |
| Rate Limiting | Enable API rate limiting | `true` |
| Party Creation Limit | Max per IP | `5 per hour` |
| API Rate Limit | Max per IP | `1000 per minute` |

**Session**

| Setting | Description | Default |
|---|---|---|
| Static Session Mode | Auto-create a fixed party on startup | `false` |
| Static Session ID | Party code when static mode is enabled | `PARTY` |

**Late Join Vote** _(new in 2.0)_

| Setting | Description | Default |
|---|---|---|
| Enable Late Join Vote | Require a majority vote to admit users who join mid-playback | `true` |
| Vote Timeout (s) | Seconds before the selector tiebreak kicks in | `20` |
| Post-Vote Cooldown (s) | Delay after a failed vote before another join attempt is allowed (0 disables) | `30` |

## Architecture

### Backend (Flask + SocketIO)
- **Flask**: Web server and REST API endpoints
- **SocketIO**: WebSocket-based real-time communication
- **EmbyClient**: Custom API client for Emby server integration with user authentication
- **HLS.js**: HTTP Live Streaming (HLS) playback support

### Frontend
- **Vanilla JavaScript**: No frameworks, just clean JS
- **Socket.IO Client**: Real-time bidirectional communication
- **HLS.js**: Advanced HLS video streaming with buffering and error recovery
- **HTML5 Video**: Native video player with custom controls

### Key Components

#### Watch Party Rooms
Each room maintains:
- List of connected users
- Current video being watched
- Playback state (playing/paused, current time)

#### Synchronization
When any user performs an action (play/pause/seek), it's broadcast to all users in the room via WebSocket, ensuring everyone stays in sync. The application uses a coordinated pause-seek-buffer-resume flow to prevent desynchronization during seeking operations.

#### Authentication & Security
The application authenticates with Emby using username/password credentials to obtain an AccessToken, which is then used for all HLS streaming requests. All media streaming goes through the Flask proxy, keeping your Emby server on your internal network and never exposed to the internet.

## API Endpoints

### REST API

- `GET /` - Home page
- `GET /party/<party_id>` - Watch party room page
- `GET /api/libraries` - Get all media libraries
- `GET /api/items?parentId=<id>&type=<type>&recursive=<bool>` - Get library items
- `GET /api/item/<item_id>` - Get item details
- `GET /api/stream/<item_id>` - Get video stream URL
- `POST /api/party/create` - Create a new watch party
- `GET /api/party/<party_id>/info` - Get party information

### WebSocket Events

**Client → Server:**
- `join_party` - Join a watch party room
- `leave_party` - Leave a watch party room
- `select_video` - Select a video to watch
- `play` - Play the video
- `pause` - Pause the video
- `seek` - Seek to a specific time
- `chat_message` - Send a chat message

**Server → Client:**
- `connected` - Connection established
- `user_joined` - A user joined the room
- `user_left` - A user left the room
- `sync_state` - Sync current playback state
- `video_selected` - A new video was selected
- `play` - Play command from another user
- `pause` - Pause command from another user
- `seek` - Seek command from another user
- `chat_message` - Chat message from another user
- `error` - Error occurred

## Troubleshooting

### Videos won't play
- Ensure the Flask app is accessible from client browsers
- Check that your username and password are correct in `.env`
- Verify the Emby server is reachable from the Flask app server (internal network)
- Verify the user account has permission to access the media
- Check the logs in `logs/emby-watchparty.log` for authentication or proxy errors

### Synchronization issues
- Check your network connection
- Make sure WebSocket connections aren't blocked by firewalls
- Try refreshing the page
- If seeking causes desync, check that all clients have stable network connections

### Can't browse library
- Verify the Emby server URL is correct in `.env`
- Check that your username and password are correct
- Ensure the Emby server is running and reachable from the Flask app (internal network)
- Verify the user account has library access permissions

## Security Notes

- **Proxy Architecture**: Your Emby server stays on your local network and is never exposed to the internet
- The Flask app proxies all HLS streaming requests, acting as a security layer between users and your Emby server
- This application authenticates with Emby using username/password credentials
- Credentials are stored in `.env` - **do not commit this file to public repositories**
- Party codes are generated using cryptographically secure random tokens
- AccessTokens are obtained at runtime and not stored persistently
- Built-in security features:
  - HLS token validation (prevents direct stream access bypass)
  - Rate limiting (prevents API abuse)
  - Configurable party size limits
- For production use, consider adding:
  - HTTPS/TLS encryption (recommended if exposing to the internet)
  - Reverse proxy (nginx, Caddy, etc.)

## License

MIT License - feel free to modify and use as you wish!

## Contributing

Contributions are welcome! Feel free to submit issues or pull requests.

## Acknowledgments

- Built with Flask and SocketIO
- Integrates with Emby Media Server
- Inspired by various watch party applications

### Special Thanks

Special thanks to **[QuackMasterDan](https://emby.media/community/index.php?/profile/1658172-quackmasterdan/)** for his dedication in testing and providing valuable feedback throughout development!

Thanks to **[wlowen](https://github.com/wlowen)** and **[JeslynMcKenzie](https://github.com/JeslynMcKenzie)** for testing, detailed bug reports, and providing mediainfo that helped track down the HEVC transcoding issue!

Thanks to **@stealthydruid** and **@xyxxyxxy** for the bug reports and feature requests on the [Discord support server](https://discord.gg/RWUpxq9xsA) that shaped the late-stage 2.0 betas.

---

### Support the Project

If you enjoy Emby Watch Party and want to support its development, consider buying me a coffee!

[![Ko-fi](https://img.shields.io/badge/Ko--fi-Support%20Development-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/jedziah)
