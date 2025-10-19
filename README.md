# Emby Watch Party

A synchronized watch party application for Emby media servers. Watch videos together with friends in real-time, no matter where you are!

## Features

- **HLS Streaming**: High-quality HTTP Live Streaming with adaptive bitrate and buffering
- **Real-time synchronization**: Watch videos together with automatic play/pause/seek synchronization
- **Library browsing**: Browse your entire Emby library and select videos to watch
- **Subtitle & Audio Support**: Automatic detection of default tracks with burned-in subtitle support
- **Room system**: Create private watch party rooms with unique codes
- **Live chat**: Chat with other viewers while watching
- **Random usernames**: Auto-generated usernames if not provided (554,400+ combinations)
- **Multiple users**: Support for unlimited concurrent viewers in a room
- **Professional logging**: rsyslog-style logging with automatic rotation
- **Responsive UI**: Modern, clean interface that works on desktop and mobile

## Setup

### Prerequisites

- Python 3.8 or higher
- An Emby server with API access
- Emby user account credentials (username and password)

### Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Configure your Emby server credentials:

Edit [config.py](config.py) or set environment variables:

**Option 1: Edit config.py (Recommended)**
```python
EMBY_SERVER_URL = 'http://your-emby-server:8096'
EMBY_USERNAME = 'your-username'
EMBY_PASSWORD = 'your-password'
```

**Option 2: Environment Variables**

**Windows (PowerShell):**
```powershell
$env:EMBY_SERVER_URL="http://your-emby-server:8096"
$env:EMBY_USERNAME="your-username"
$env:EMBY_PASSWORD="your-password"
```

**Windows (Command Prompt):**
```cmd
set EMBY_SERVER_URL=http://your-emby-server:8096
set EMBY_USERNAME=your-username
set EMBY_PASSWORD=your-password
```

**Linux/Mac:**
```bash
export EMBY_SERVER_URL="http://your-emby-server:8096"
export EMBY_USERNAME="your-username"
export EMBY_PASSWORD="your-password"
```

3. Run the application:
```bash
python app.py
```

4. Open your browser and navigate to:
```
http://localhost:5000
```

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

You can configure the application in [config.py](config.py) or using environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `EMBY_SERVER_URL` | Your Emby server URL | `http://central.andrew.home` |
| `EMBY_USERNAME` | Your Emby username | `andrew` |
| `EMBY_PASSWORD` | Your Emby password | `andrew` |
| `LOG_LEVEL` | Logging level (DEBUG, INFO, WARNING, ERROR) | `INFO` |
| `LOG_FILE` | Path to log file | `logs/emby-watchparty.log` |
| `CONSOLE_LOG_LEVEL` | Console log level | `WARNING` |

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

#### Authentication
The application authenticates with Emby using username/password credentials to obtain an AccessToken, which is then used for all HLS streaming requests. This ensures secure access to your media library.

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
- Ensure your Emby server is accessible from the client browsers
- Check that your username and password are correct in [config.py](config.py)
- Verify the user account has permission to access the media
- Check the logs in `logs/emby-watchparty.log` for authentication errors

### Synchronization issues
- Check your network connection
- Make sure WebSocket connections aren't blocked by firewalls
- Try refreshing the page
- If seeking causes desync, check that all clients have stable network connections

### Can't browse library
- Verify the Emby server URL is correct in [config.py](config.py)
- Check that your username and password are correct
- Ensure the Emby server is running and accessible
- Verify the user account has library access permissions

## Security Notes

- This application authenticates with Emby using username/password credentials
- Credentials are stored in [config.py](config.py) - **do not commit this file to public repositories**
- Party codes are generated using cryptographically secure random tokens
- AccessTokens are obtained at runtime and not stored persistently
- For production use, consider adding:
  - HTTPS/TLS encryption
  - User authentication for watch party access
  - Rate limiting
  - CORS restrictions
  - Environment variable-based credential management instead of config.py

## License

MIT License - feel free to modify and use as you wish!

## Contributing

Contributions are welcome! Feel free to submit issues or pull requests.

## Acknowledgments

- Built with Flask and SocketIO
- Integrates with Emby Media Server
- Inspired by various watch party applications
