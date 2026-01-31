# Emby Watch Party

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![Flask](https://img.shields.io/badge/flask-3.0.0-green.svg)](https://flask.palletsprojects.com/)
[![GitHub release](https://img.shields.io/github/release/Oratorian/emby-watchparty.svg)](https://github.com/Oratorian/emby-watchparty/releases)
[![GitHub stars](https://img.shields.io/github/stars/Oratorian/emby-watchparty.svg)](https://github.com/Oratorian/emby-watchparty/stargazers)

A synchronized watch party application for Emby media servers. Watch videos together with friends in real-time, no matter where you are!

---

### 🎉 Special Thanks

Special thanks to **[QuackMasterDan](https://emby.media/community/index.php?/profile/1658172-quackmasterdan/)** for his dedication in testing and providing valuable feedback throughout development!

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
EMBY_SERVER_URL=http://your-emby-server:8096
EMBY_API_KEY=your-api-key-here
EMBY_USERNAME=your-username
EMBY_PASSWORD=your-password

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
  -e EMBY_USERNAME=your-username \
  -e EMBY_PASSWORD=your-password \
  -e LOG_TO_FILE=false \
  ghcr.io/oratorian/emby-watchparty:latest
```

**Note:** For Docker deployments, set `LOG_TO_FILE=false` to output logs to stdout only.

## Usage

### Creating a Watch Party

1. Click **"Create Party"** on the home page
2. Share the party code with your friends
3. Browse the Emby library and select a video
4. Everyone in the room will be synchronized!

### Joining a Watch Party

1. Click **"Join Watch Party"** on the home page
2. Enter the party code you received
3. Enter your username
4. Start watching together!

### Controls

- **Browse Library**: Use the sidebar to browse your Emby libraries, movies, and TV shows
- **Select Video**: Click on any video to start watching it with the group
- **Video Controls**: The host (or any user) can play, pause, or seek - all users will sync
- **Chat**: Use the chat box at the bottom to communicate with other viewers
- **Leave**: Click the "Leave" button to exit the watch party

## Configuration

All configuration is done via the `.env` file. Copy `.env.example` to `.env` and customize:

| Variable | Description | Default |
|----------|-------------|---------|
| **Application** | | |
| `WATCH_PARTY_BIND` | IP address to bind to | `0.0.0.0` |
| `WATCH_PARTY_PORT` | Port to run on | `5000` |
| `REQUIRE_LOGIN` | Require Emby login to access | `false` |
| `SESSION_EXPIRY` | Session expiry in seconds | `86400` |
| **Emby Server** | | |
| `EMBY_SERVER_URL` | Your Emby server URL | `http://localhost:8096` |
| `EMBY_API_KEY` | Emby API key | (required) |
| `EMBY_USERNAME` | Your Emby username | (required) |
| `EMBY_PASSWORD` | Your Emby password | (required) |
| **Logging** | | |
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | `INFO` |
| `LOG_TO_FILE` | Enable file logging (`true`/`false`) | `true` |
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
