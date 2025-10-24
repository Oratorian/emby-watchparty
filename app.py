"""
Emby Watch Party - Synchronized video watching for Emby media server
Author: Oratorian
GitHub: https://github.com/Oratorian
Description: A Flask-based web application that allows multiple users to watch
             Emby media in sync with real-time chat and playback synchronization.
             Supports HLS streaming with proper authentication.
"""

from flask import Flask, render_template, request, jsonify, session
from flask_socketio import SocketIO, emit, join_room, leave_room, rooms
import requests
from datetime import datetime, timedelta
import secrets
import random
import os
import sys
import time
import hashlib

sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'logger'))
from logger import setup_logger
import config

# Application version
VERSION = "1.1.0"

# Import frequently used config values as module-level constants for convenience
EMBY_SERVER_URL = config.EMBY_SERVER_URL
EMBY_API_KEY = config.EMBY_API_KEY
EMBY_USERNAME = config.EMBY_USERNAME
EMBY_PASSWORD = config.EMBY_PASSWORD

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(16)

logger = setup_logger("emby-watchparty")
socketio_logger = setup_logger(
    name="socketio",
    log_file="logs/socketio.log",
    log_level="WARNING"  # Only log warnings/errors from Socket.IO
)
engineio_logger = setup_logger(
    name="engineio",
    log_file="logs/socketio.log",  # Same file as socketio
    log_level="WARNING"  # Only log warnings/errors from Engine.IO
)

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    logger=socketio_logger,  # Redirect to separate log file
    engineio_logger=engineio_logger  # Redirect to separate log file
)

# Redirect Flask/Werkzeug HTTP access logs to use custom logger
import logging

# Get Werkzeug's logger and REMOVE its default console handler
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.handlers.clear()  # Remove default console handler

# Replace with our custom logger that writes to file
werkzeug_custom_logger = setup_logger(
    name="werkzeug",
    log_file="logs/access.log",
    log_level="INFO"  # Log all HTTP requests to file
)

# Initialize rate limiter if enabled
if config.ENABLE_RATE_LIMITING:
    try:
        from flask_limiter import Limiter
        from flask_limiter.util import get_remote_address
        limiter = Limiter(
            app=app,
            key_func=get_remote_address,
            default_limits=[config.RATE_LIMIT_API_CALLS],
            storage_uri="memory://"
        )
        logger.info("Rate limiting enabled")
    except ImportError:
        logger.error("ENABLE_RATE_LIMITING is set to true, but Flask-Limiter is not installed!")
        logger.error("Install with: pip install Flask-Limiter")
        logger.error("Or disable rate limiting by setting ENABLE_RATE_LIMITING=false in config")
        sys.exit(1)  # Exit with error code
else:
    limiter = None
    logger.info("Rate limiting disabled (ENABLE_RATE_LIMITING=false)")

"""
Global watch party storage.

Dictionary mapping party_id to party data containing users, current video,
and playback state. Structure:
    {
        'party_id': {
            'id': str,
            'created_at': str (ISO format),
            'users': {socket_id: username},
            'current_video': {
                'item_id': str,
                'title': str,
                'overview': str,
                'stream_url_base': str (without token),
                'audio_index': int,
                'subtitle_index': int
            },
            'playback_state': {
                'playing': bool,
                'time': float,
                'last_update': str (ISO format)
            }
        }
    }
"""
watch_parties = {}

"""
HLS token storage for secure stream validation.

Dictionary mapping token strings to token metadata. Tokens are per-user
and expire after HLS_TOKEN_EXPIRY seconds. Structure:
    {
        'token_string': {
            'party_id': str,
            'sid': str (socket session ID),
            'expires': float (Unix timestamp)
        }
    }
"""
hls_tokens = {}

"""Word lists for generating random usernames (e.g., 'BraveWolf42')."""
ADJECTIVES = [
    'Happy', 'Sleepy', 'Brave', 'Clever', 'Swift', 'Mighty', 'Gentle', 'Wise', 'Lucky', 'Bold',
    'Silent', 'Wild', 'Calm', 'Fierce', 'Noble', 'Quick', 'Bright', 'Dark', 'Golden', 'Silver',
    'Ancient', 'Young', 'Mystic', 'Cosmic', 'Thunder', 'Lightning', 'Storm', 'Frost', 'Fire', 'Shadow',
    'Crimson', 'Azure', 'Jade', 'Ruby', 'Diamond', 'Steel', 'Iron', 'Crystal', 'Blazing', 'Frozen',
    'Electric', 'Savage', 'Loyal', 'Royal', 'Stellar', 'Lunar', 'Solar', 'Astral', 'Phantom', 'Spirit',
    'Mighty', 'Mega', 'Super', 'Ultra', 'Hyper', 'Quantum', 'Cyber', 'Ninja', 'Samurai', 'Warrior',
    'Epic', 'Legendary', 'Mythic', 'Sacred', 'Divine', 'Radiant', 'Glowing', 'Shining', 'Sparkling', 'Dazzling'
]
NOUNS = [
    'Panda', 'Tiger', 'Eagle', 'Dolphin', 'Fox', 'Wolf', 'Bear', 'Hawk', 'Lion', 'Owl',
    'Dragon', 'Phoenix', 'Falcon', 'Raven', 'Panther', 'Jaguar', 'Leopard', 'Cheetah', 'Lynx', 'Cougar',
    'Shark', 'Whale', 'Orca', 'Kraken', 'Serpent', 'Viper', 'Cobra', 'Python', 'Anaconda', 'Komodo',
    'Griffin', 'Pegasus', 'Unicorn', 'Chimera', 'Hydra', 'Sphinx', 'Minotaur', 'Centaur', 'Titan', 'Golem',
    'Samurai', 'Ninja', 'Ronin', 'Shogun', 'Sensei', 'Monk', 'Knight', 'Paladin', 'Archer', 'Ranger',
    'Wizard', 'Sorcerer', 'Mage', 'Warlock', 'Shaman', 'Druid', 'Sage', 'Oracle', 'Prophet', 'Mystic',
    'Valkyrie', 'Guardian', 'Sentinel', 'Watcher', 'Protector', 'Defender', 'Champion', 'Hero', 'Legend', 'Warrior',
    'Ghost', 'Specter', 'Wraith', 'Phantom', 'Spirit', 'Shade', 'Reaper', 'Revenant', 'Banshee', 'Demon'
]

def generate_random_username():
    """Generate a random username like 'HappyPanda' or 'BraveTiger'"""
    adjective = random.choice(ADJECTIVES)
    noun = random.choice(NOUNS)
    number = random.randint(1, 99)
    return f"{adjective}{noun}{number}"


def generate_party_code():
    """
    Generate a simple 5-character alphanumeric party code.
    Uses uppercase letters and numbers, excluding confusing characters (0, O, 1, I, L).
    Returns codes like: A3B7K, 9XR4P, etc.
    """
    # Character set without confusing characters
    chars = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'

    # Keep generating until we find a unique code
    max_attempts = 100
    for _ in range(max_attempts):
        code = ''.join(random.choice(chars) for _ in range(5))
        if code not in watch_parties:
            return code

    # Fallback to longer code if somehow we can't find a unique 5-digit code
    logger.warning("Could not generate unique 5-character code after 100 attempts, using longer code")
    return secrets.token_urlsafe(8)


class EmbyClient:
    """Client for interacting with Emby Server API"""

    def __init__(self, server_url, api_key, username=None, password=None):
        """
        Initialize Emby client with server connection details.

        Args:
            server_url: Base URL of the Emby server
            api_key: API key for Emby authentication
            username: Optional username for user-specific authentication
            password: Optional password for user-specific authentication
        """
        self.server_url = server_url.rstrip('/')
        self.api_key = api_key
        self.headers = {
            'X-Emby-Token': api_key,
            'Content-Type': 'application/json'
        }
        self.user_id = None
        self.access_token = None
        self.device_id = "emby-watchparty-" + secrets.token_hex(8)

        # If username/password provided, authenticate as that user
        if username and password:
            self._authenticate_user(username, password)
        else:
            self._fetch_user_id()

    def _authenticate_user(self, username, password):
        """Authenticate as a specific user and get access token"""
        try:
            url = f"{self.server_url}/emby/Users/AuthenticateByName"
            headers = {
                'Content-Type': 'application/json',
                'X-Emby-Authorization': f'Emby Client="WatchParty", Device="Web", DeviceId="{self.device_id}", Version="1.0"'
            }
            payload = {
                'Username': username,
                'Pw': password
            }

            response = requests.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

            # Extract access token and user ID
            self.access_token = data.get('AccessToken')
            self.user_id = data.get('User', {}).get('Id')

            # Update headers to use access token
            if self.access_token:
                self.api_key = self.access_token
                self.headers = {
                    'X-Emby-Token': self.access_token,
                    'Content-Type': 'application/json',
                    'X-Emby-Authorization': f'Emby UserId="{self.user_id}", Client="WatchParty", Device="Web", DeviceId="{self.device_id}", Version="1.0", Token="{self.access_token}"'
                }

            logger.info(f"Authenticated as user: {data.get('User', {}).get('Name', 'Unknown')} (ID: {self.user_id})")
            logger.debug(f"Access Token: {self.access_token[:20]}..." if self.access_token else "No access token")

        except Exception as e:
            logger.error(f"Error authenticating user: {e}")
            logger.warning("Falling back to API key authentication")
            self._fetch_user_id()

    def _fetch_user_id(self):
        """Fetch a user ID to use for API calls that require user context"""
        try:
            # Get list of users
            url = f"{self.server_url}/emby/Users"
            params = {'api_key': self.api_key}
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            users = response.json()

            if users and len(users) > 0:
                # Use the first user (usually the admin)
                self.user_id = users[0]['Id']
                logger.info(f"Using Emby user: {users[0].get('Name', 'Unknown')} (ID: {self.user_id})")
            else:
                logger.warning("No Emby users found, some features may not work")
        except Exception as e:
            logger.error(f"Error fetching user ID: {e}")
            logger.warning("Some API features may not work without user context")

    def get_libraries(self):
        """Get all media libraries"""
        try:
            url = f"{self.server_url}/emby/Library/MediaFolders"
            response = requests.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching libraries: {e}")
            return {"Items": []}

    def get_items(self, parent_id=None, item_type=None, recursive=False):
        """Get items from library"""
        try:
            url = f"{self.server_url}/emby/Items"
            params = {
                'Recursive': str(recursive).lower(),
                'Fields': 'Overview,PrimaryImageAspectRatio,ProductionYear'
            }

            if parent_id:
                params['ParentId'] = parent_id

            if item_type:
                params['IncludeItemTypes'] = item_type

            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error fetching items: {e}")
            return {"Items": []}

    def get_item_details(self, item_id):
        """Get detailed information about a specific item"""
        if not self.user_id:
            logger.warning("No user ID available for item details request")
            return None

        try:
            # Use user-specific endpoint which is more reliable
            url = f"{self.server_url}/emby/Users/{self.user_id}/Items/{item_id}"
            params = {'api_key': self.api_key}
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                # Try direct Items endpoint as fallback
                try:
                    url = f"{self.server_url}/emby/Items/{item_id}"
                    params = {'api_key': self.api_key}
                    response = requests.get(url, headers=self.headers, params=params)
                    response.raise_for_status()
                    return response.json()
                except Exception as e2:
                    logger.error(f"Error fetching item details from Items endpoint: {e2}")
            logger.error(f"Error fetching item details: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching item details: {e}")
            return None

    def search_items(self, query):
        """Search for items by name"""
        if not self.user_id:
            logger.warning("No user ID available for search request")
            return {"Items": []}

        try:
            url = f"{self.server_url}/emby/Users/{self.user_id}/Items"
            params = {
                'SearchTerm': query,
                'Recursive': 'true',
                'Fields': 'Overview,PrimaryImageAspectRatio,ProductionYear',
                'IncludeItemTypes': 'Movie,Series',
                'api_key': self.api_key
            }
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.error(f"Error searching items: {e}")
            return {"Items": []}

    def get_image_url(self, item_id, image_type='Primary'):
        """Get image URL for an item"""
        return f"{self.server_url}/emby/Items/{item_id}/Images/{image_type}?api_key={self.api_key}"

    def get_playback_info(self, item_id):
        """Get playback information including MediaSourceId and PlaySessionId"""
        if not self.user_id:
            logger.warning("No user ID available for playback info request")
            return None

        try:
            # Use POST request to PlaybackInfo endpoint as per Emby API
            url = f"{self.server_url}/emby/Items/{item_id}/PlaybackInfo"
            params = {
                'UserId': self.user_id,
                'api_key': self.api_key
            }
            response = requests.post(url, headers=self.headers, params=params, json={})
            response.raise_for_status()
            data = response.json()

            # Extract important info
            if data and 'MediaSources' in data and data['MediaSources']:
                media_source = data['MediaSources'][0]
                logger.debug(f"PlaybackInfo - MediaSourceId: {media_source.get('Id')}, PlaySessionId: {data.get('PlaySessionId')}")

            return data
        except Exception as e:
            logger.error(f"Error fetching playback info: {e}")
            # Fallback to trying to get item details which may have MediaStreams
            return self.get_item_details(item_id)

    def stop_active_encodings(self):
        """
        Stop all active HLS transcoding sessions for this device.
        Should be called when playback stops to free up server resources.

        Per Emby API: After playback is complete, it is necessary to inform
        the server to stop any related HLS transcoding.
        """
        try:
            url = f"{self.server_url}/emby/Videos/ActiveEncodings"
            params = {
                'DeviceId': self.device_id,
                'api_key': self.api_key
            }
            response = requests.delete(url, headers=self.headers, params=params)
            response.raise_for_status()
            logger.debug(f"Stopped active encodings for device {self.device_id}")
            return True
        except Exception as e:
            logger.warning(f"Failed to stop active encodings: {e}")
            return False


emby_client = EmbyClient(EMBY_SERVER_URL, EMBY_API_KEY, EMBY_USERNAME, EMBY_PASSWORD)


# =============================================================================
# Security Helper Functions
# =============================================================================

def generate_hls_token(party_id, sid):
    """Generate a time-limited token for HLS stream access"""
    if not config.ENABLE_HLS_TOKEN_VALIDATION:
        logger.debug("HLS token generation skipped - validation disabled")
        return None

    token = secrets.token_urlsafe(32)
    expires = time.time() + config.HLS_TOKEN_EXPIRY
    expires_dt = datetime.fromtimestamp(expires).isoformat()

    hls_tokens[token] = {
        'party_id': party_id,
        'sid': sid,
        'expires': expires
    }

    logger.debug(f"Generated HLS token: {token[:16]}... for party={party_id}, sid={sid}, expires={expires_dt}")
    logger.debug(f"Total active tokens: {len(hls_tokens)}")

    # Clean up expired tokens
    cleanup_expired_tokens()

    return token


def validate_hls_token(token, item_id=None):
    """Validate HLS token and return party_id if valid"""
    if not config.ENABLE_HLS_TOKEN_VALIDATION:
        return True  # Token validation disabled

    if not token:
        logger.debug("Token validation failed: No token provided")
        return False

    if token not in hls_tokens:
        logger.debug(f"Token validation failed: Token not found: {token[:16]}...")
        logger.debug(f"Available tokens: {[t[:16] + '...' for t in list(hls_tokens.keys())[:5]]}")
        return False

    token_data = hls_tokens[token]

    # Check if token expired
    if time.time() > token_data['expires']:
        logger.debug(f"Token validation failed: Token expired")
        del hls_tokens[token]
        return False

    # Check if user is still in the party
    party_id = token_data['party_id']
    sid = token_data['sid']

    if party_id not in watch_parties:
        logger.debug(f"Token validation failed: Party {party_id} not found. Available parties: {list(watch_parties.keys())}")
        return False

    if sid not in watch_parties[party_id]['users']:
        logger.debug(f"Token validation failed: User sid {sid} not in party {party_id}. Current user sids: {list(watch_parties[party_id]['users'].keys())}")
        return False

    logger.debug(f"Token validation successful for party {party_id}, user {sid}")
    return True


def cleanup_expired_tokens():
    """Remove expired HLS tokens"""
    current_time = time.time()
    expired = [token for token, data in hls_tokens.items() if current_time > data['expires']]
    if expired:
        logger.debug(f"Cleaning up {len(expired)} expired HLS tokens")
        for token in expired:
            logger.debug(f"Removed expired token: {token[:16]}... (party={hls_tokens[token]['party_id']}, sid={hls_tokens[token]['sid']})")
            del hls_tokens[token]


def get_user_token(party_id, sid):
    """Get existing valid token for user or generate new one"""
    # Find existing valid token for this user
    for token, data in hls_tokens.items():
        if data['party_id'] == party_id and data['sid'] == sid:
            if time.time() <= data['expires']:
                logger.debug(f"Reusing existing token for party {party_id}, sid {sid}")
                return token

    # Generate new token
    new_token = generate_hls_token(party_id, sid)
    if new_token:
        logger.debug(f"Generated new token for party {party_id}, sid {sid}: {new_token[:16]}...")
    return new_token


# =============================================================================
# Web Routes
# =============================================================================

@app.route('/')
def index():
    """Main page - choose to create or join a watch party"""
    return render_template('index.html')


@app.route('/party/<party_id>')
def party(party_id):
    """Watch party room page"""
    # Convert to uppercase for case-insensitive matching
    party_id = party_id.upper()

    if party_id not in watch_parties:
        return render_template('error.html',
                             party_id=party_id,
                             message="The watch party you're looking for doesn't exist or has ended."), 404
    return render_template('party.html', party_id=party_id)


# =============================================================================
# API Routes
# =============================================================================
"""
REST API endpoints for building custom frontends.

All endpoints return JSON unless otherwise specified.
Rate limiting applies to some endpoints when ENABLE_RATE_LIMITING=true.

Library & Media Endpoints:
    GET  /api/libraries           - List all Emby libraries
    GET  /api/items               - List items (with filters)
    GET  /api/search              - Search for content
    GET  /api/item/<id>           - Get item details
    GET  /api/item/<id>/streams   - Get audio/subtitle streams
    GET  /api/image/<id>          - Get item poster/thumbnail

Party Management Endpoints:
    POST /api/party/create        - Create new watch party
    GET  /api/party/<id>/info     - Get party state

HLS Streaming Endpoints (Token Protected):
    GET  /hls/<id>/master.m3u8    - HLS master playlist
    GET  /hls/<id>/<path>          - HLS segments/playlists
"""

@app.route('/api/libraries')
def api_libraries():
    """
    Get all media libraries from Emby server.

    Returns:
        JSON: {
            "Items": [
                {
                    "Id": str,
                    "Name": str,
                    "CollectionType": str ("movies", "tvshows", etc.)
                }
            ]
        }

    Example:
        GET /api/libraries
    """
    libraries = emby_client.get_libraries()
    return jsonify(libraries)


@app.route('/api/items')
def api_items():
    """
    Get items from a library (movies, series, episodes, seasons).

    Query Parameters:
        parentId (str, optional): Filter by parent library/series/season ID
        type (str, optional): Filter by type ("Movie", "Series", etc.)
        recursive (bool, optional): Include child items recursively

    Returns:
        JSON: {
            "Items": [
                {
                    "Id": str,
                    "Name": str,
                    "Type": str,
                    "Overview": str,
                    "ProductionYear": int
                }
            ]
        }

    Examples:
        GET /api/items?parentId=12345
        GET /api/items?type=Movie&recursive=true
    """
    parent_id = request.args.get('parentId')
    item_type = request.args.get('type')
    recursive = request.args.get('recursive', 'false').lower() == 'true'

    items = emby_client.get_items(parent_id, item_type, recursive)
    return jsonify(items)


@app.route('/api/search')
def api_search():
    """
    Search for movies and TV series by name.

    Query Parameters:
        q (str, required): Search query string

    Returns:
        JSON: {
            "Items": [
                {
                    "Id": str,
                    "Name": str,
                    "Type": str ("Movie" or "Series"),
                    "Overview": str,
                    "ProductionYear": int
                }
            ]
        }

    Examples:
        GET /api/search?q=inception
        GET /api/search?q=breaking+bad
    """
    query = request.args.get('q', '').strip()

    if not query:
        return jsonify({"Items": []})

    results = emby_client.search_items(query)
    return jsonify(results)


@app.route('/api/item/<item_id>')
def api_item_details(item_id):
    """
    Get detailed information for a specific item.

    Path Parameters:
        item_id (str): Emby item ID

    Returns:
        JSON: {
            "Id": str,
            "Name": str,
            "Type": str,
            "Overview": str,
            "ProductionYear": int,
            "MediaStreams": [...]
        }

    Errors:
        404: Item not found

    Example:
        GET /api/item/12345
    """
    details = emby_client.get_item_details(item_id)
    if details:
        return jsonify(details)
    return jsonify({"error": "Item not found"}), 404


@app.route('/api/item/<item_id>/streams')
def api_item_streams(item_id):
    """
    Get available audio and subtitle streams for a media item.

    Path Parameters:
        item_id (str): Emby item ID

    Returns:
        JSON: {
            "audio": [
                {
                    "index": int,
                    "language": str,
                    "displayLanguage": str,
                    "codec": str,
                    "channels": int,
                    "isDefault": bool,
                    "title": str
                }
            ],
            "subtitles": [
                {
                    "index": int,
                    "language": str,
                    "displayLanguage": str,
                    "codec": str,
                    "isDefault": bool,
                    "isForced": bool,
                    "isExternal": bool,
                    "title": str
                }
            ]
        }

    Example:
        GET /api/item/<item_id>/streams
    """
    logger.debug(f"Fetching streams for item ID: {item_id}")

    # Try multiple approaches to get stream information
    playback_info = None

    # Method 1: Try PlaybackInfo endpoint
    playback_info = emby_client.get_playback_info(item_id)

    # Method 2: If that fails, try getting item details directly
    if not playback_info:
        playback_info = emby_client.get_item_details(item_id)

    # Method 3: Try using the streaming endpoint directly to infer info
    if not playback_info:
        logger.warning(f"Could not fetch item info via API, trying stream endpoint...")
        try:
            # Make a HEAD request to the stream endpoint to see if it exists
            stream_url = f"{EMBY_SERVER_URL}/emby/Videos/{item_id}/stream.mp4?api_key={emby_client.api_key}"
            response = requests.head(stream_url, timeout=5)
            if response.status_code == 200:
                logger.info(f"Stream exists but no item metadata available - returning defaults")
                # Return minimal stream info - just use defaults
                return jsonify({
                    "audio": [],
                    "subtitles": [],
                    "note": "Stream info not available - using default settings"
                })
        except Exception as e:
            logger.error(f"Stream endpoint check failed: {e}")

    if not playback_info:
        logger.error("All methods failed to get stream info")
        return jsonify({"error": "Could not fetch stream information", "audio": [], "subtitles": []}), 200

    audio_streams = []
    subtitle_streams = []
    media_source_id = None

    # Extract media streams - could be at different locations depending on endpoint
    media_streams = []

    # Check if we got PlaybackInfo response
    if 'MediaSources' in playback_info and playback_info['MediaSources']:
        media_streams = playback_info['MediaSources'][0].get('MediaStreams', [])
        media_source_id = playback_info['MediaSources'][0].get('Id')
    # Otherwise check for direct MediaStreams
    elif 'MediaStreams' in playback_info:
        media_streams = playback_info['MediaStreams']

    logger.debug(f"Found {len(media_streams)} media streams for item {item_id}")

    for stream in media_streams:
        stream_type = stream.get('Type')

        if stream_type == 'Audio':
            lang = stream.get('Language', 'und')
            display_lang = stream.get('DisplayLanguage') or stream.get('DisplayTitle') or lang
            if lang == 'und':
                display_lang = 'Unknown'

            audio_streams.append({
                'index': stream.get('Index'),
                'language': lang,
                'displayLanguage': display_lang,
                'codec': stream.get('Codec', ''),
                'channels': stream.get('Channels', 0),
                'isDefault': stream.get('IsDefault', False),
                'title': stream.get('Title', '')
            })
        elif stream_type == 'Subtitle':
            is_text_subtitle = stream.get('IsTextSubtitleStream', False)
            codec = stream.get('Codec', '').lower()

            # Detect image-based subtitle formats (PGS, VobSub)
            is_image_subtitle = codec in ['pgssub', 'pgs', 'dvd_subtitle', 'dvdsub', 'vobsub']

            lang = stream.get('Language', 'und')
            display_lang = stream.get('DisplayLanguage') or stream.get('DisplayTitle') or lang
            if lang == 'und':
                display_lang = 'Unknown'

            subtitle_streams.append({
                'index': stream.get('Index'),
                'language': lang,
                'displayLanguage': display_lang,
                'codec': stream.get('Codec', ''),
                'isDefault': stream.get('IsDefault', False),
                'isForced': stream.get('IsForced', False),
                'isExternal': stream.get('IsExternal', False),
                'isTextSubtitleStream': is_text_subtitle,
                'isPGS': is_image_subtitle,  # Mark image-based subs for burn-in
                'title': stream.get('Title', '')
            })

    logger.debug(f"Processed {len(audio_streams)} audio streams and {len(subtitle_streams)} subtitle streams")

    return jsonify({
        'audio': audio_streams,
        'subtitles': subtitle_streams,
        'media_source_id': media_source_id
    })

@app.route('/api/intro/<item_id>', methods=['GET'])
def get_intro_info(item_id):
    """
    Get intro timing information for a specific item.

    Returns intro start/end times in seconds if available,
    or indicates no intro data exists.

    Response format:
        {
            "hasIntro": bool,
            "start": float (seconds),
            "end": float (seconds),
            "duration": float (seconds)
        }

    Example:
        GET /api/intro/63359
        Returns: {"hasIntro": true, "start": 90.67, "end": 138.56, "duration": 47.89}
    """
    logger.debug(f"Fetching intro info for item ID: {item_id}")

    try:
        # Fetch all intro data from Emby's Chapter API plugin
        # Note: This endpoint requires admin access, so we use API key directly
        response = requests.get(
            f"{EMBY_SERVER_URL}/emby/Items/Intros",
            params={"api_key": EMBY_API_KEY},
            headers={'Content-Type': 'application/json'},
            timeout=5
        )

        if response.status_code == 200:
            all_intros = response.json()

            # Find intro for this specific item
            for intro in all_intros:
                if str(intro.get('Id')) == str(item_id):
                    # Convert ticks (100-nanosecond units) to seconds
                    # 1 second = 10,000,000 ticks
                    start_seconds = intro.get('Start', 0) / 10_000_000
                    end_seconds = intro.get('End', 0) / 10_000_000

                    logger.info(f"Found intro for item {item_id}: {start_seconds:.2f}s - {end_seconds:.2f}s")

                    return jsonify({
                        'hasIntro': True,
                        'start': start_seconds,
                        'end': end_seconds,
                        'duration': end_seconds - start_seconds
                    })

            # No intro found for this item
            logger.debug(f"No intro data found for item {item_id}")
            return jsonify({'hasIntro': False})
        else:
            logger.warning(f"Failed to fetch intro data from Emby: HTTP {response.status_code}")
            return jsonify({'hasIntro': False})

    except requests.exceptions.Timeout:
        logger.error(f"Timeout fetching intro info for item {item_id}")
        return jsonify({'hasIntro': False})
    except Exception as e:
        logger.error(f"Error fetching intro info for item {item_id}: {e}")
        return jsonify({'hasIntro': False})

@app.route('/hls/<item_id>/master.m3u8')
def proxy_hls_master(item_id):
    """Lightweight HLS master playlist proxy - keeps Emby internal"""
    emby_url = None  # Initialize for error handling
    try:
        from flask import Response
        import re

        # Validate HLS token if enabled
        if config.ENABLE_HLS_TOKEN_VALIDATION:
            token = request.args.get('token')
            logger.debug(f"Master playlist request with token: {token[:16] if token else 'None'}... from {request.remote_addr}")
            if not validate_hls_token(token):
                logger.warning(f"Invalid or missing HLS token for master playlist access from {request.remote_addr}")
                return jsonify({"error": "Unauthorized"}), 401

        # Forward all query parameters from client (except our token)
        query_params = {k: v for k, v in request.args.items() if k != 'token'}
        query_string = '&'.join([f"{k}={v}" for k, v in query_params.items()])

        # Build Emby URL
        emby_url = f"{EMBY_SERVER_URL}/emby/Videos/{item_id}/master.m3u8"
        if query_string:
            emby_url += f"?{query_string}"

        logger.debug(f"Proxying HLS master: {emby_url}")

        # Fetch from Emby (internal network only)
        emby_response = requests.get(emby_url, headers=emby_client.headers)
        emby_response.raise_for_status()
        logger.debug(f"Received master playlist from Emby, content length: {len(emby_response.text)} bytes")
        logger.debug(f"Master playlist content:\n{emby_response.text}")

        # Rewrite URLs in the playlist to point to our proxy
        playlist_content = emby_response.text

        # Add token to rewritten URLs if validation is enabled
        token_param = f"?token={request.args.get('token')}" if config.ENABLE_HLS_TOKEN_VALIDATION and request.args.get('token') else ""
        if token_param:
            logger.debug(f"Will add token parameter: {token_param[:30]}...")
        else:
            logger.debug("No token parameter (validation disabled or no token)")

        # Replace absolute Emby URLs with proxy URLs
        # Pattern: http://server/emby/Videos/ITEMID/path → /hls/ITEMID/path?token=...
        before_rewrite = playlist_content
        playlist_content = re.sub(
            rf'{re.escape(EMBY_SERVER_URL)}/emby/Videos/{item_id}/',
            f'/hls/{item_id}/',
            playlist_content
        )
        if before_rewrite != playlist_content:
            logger.debug("Rewrote absolute Emby URLs to proxy URLs")

        # Also handle relative URLs that might start with just the path
        # Pattern: /emby/Videos/ITEMID/path → /hls/ITEMID/path?token=...
        before_rewrite = playlist_content
        playlist_content = re.sub(
            rf'/emby/Videos/{item_id}/',
            f'/hls/{item_id}/',
            playlist_content
        )
        if before_rewrite != playlist_content:
            logger.debug("Rewrote relative Emby URLs to proxy URLs")

        # Add token parameter to all segment URLs if needed
        if token_param:
            logger.debug(f"Master playlist before token addition:\n{playlist_content}")
            # Add token to .m3u8 and .ts file references
            # Match filenames ending with .m3u8 or .ts (not already having token param)
            lines = playlist_content.split('\n')
            for i, line in enumerate(lines):
                # Skip comment lines and empty lines
                if line.strip().startswith('#') or not line.strip():
                    continue
                # If line contains .m3u8 or .ts and doesn't have token already
                if ('.m3u8' in line or '.ts' in line) and 'token=' not in line:
                    # Use & if URL already has query params, otherwise use ?
                    separator = '&' if '?' in line else '?'
                    token_to_add = f"{separator}token={request.args.get('token')}"
                    old_line = line
                    lines[i] = line + token_to_add
                    logger.debug(f"Token addition: '{old_line}' -> '{lines[i]}'")
            playlist_content = '\n'.join(lines)
            logger.debug(f"Master playlist after token addition:\n{playlist_content}")
        else:
            logger.debug("Skipping token addition (no token available)")

        logger.debug(f"Rewritten playlist URLs to use /hls/{item_id}/ prefix and added tokens")

        # Return with CORS headers
        response = Response(playlist_content, mimetype='application/vnd.apple.mpegurl')
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Range'

        return response

    except requests.exceptions.RequestException as e:
        logger.error(f"CRITICAL: Failed to fetch master playlist from Emby server")
        logger.error(f"  Item ID: {item_id}")
        logger.error(f"  Emby URL: {emby_url if emby_url else '(URL not constructed)'}")
        logger.error(f"  Error: {str(e)}")
        logger.error(f"  Error Type: {type(e).__name__}")
        return jsonify({"error": "Failed to fetch video from media server"}), 502
    except Exception as e:
        logger.error(f"CRITICAL: Unexpected error in HLS master playlist proxy")
        logger.error(f"  Item ID: {item_id}")
        logger.error(f"  Error: {str(e)}")
        logger.error(f"  Error Type: {type(e).__name__}")
        import traceback
        logger.error(f"  Traceback: {traceback.format_exc()}")
        return jsonify({"error": "Internal server error"}), 500


@app.route('/hls/<item_id>/<path:subpath>')
def proxy_hls_segment(item_id, subpath):
    """Lightweight HLS segment/playlist proxy - keeps Emby internal"""
    emby_url = None  # Initialize for error handling
    try:
        from flask import Response
        import re

        # Validate HLS token if enabled
        if config.ENABLE_HLS_TOKEN_VALIDATION:
            token = request.args.get('token')
            logger.debug(f"Segment request for {subpath} with token: {token[:16] if token else 'None'}... from {request.remote_addr}")
            if not validate_hls_token(token):
                logger.warning(f"Invalid or missing HLS token for segment access: {subpath} from {request.remote_addr}")
                return jsonify({"error": "Unauthorized"}), 401

        # Forward all query parameters (except our token)
        query_params = {k: v for k, v in request.args.items() if k != 'token'}
        query_string = '&'.join([f"{k}={v}" for k, v in query_params.items()])

        emby_url = f"{EMBY_SERVER_URL}/emby/Videos/{item_id}/{subpath}"
        if query_string:
            emby_url += f"?{query_string}"

        logger.debug(f"Proxying HLS segment: {subpath} -> {emby_url}")

        # Fetch from Emby (internal network only)
        emby_response = requests.get(emby_url, headers=emby_client.headers, stream=True)
        emby_response.raise_for_status()

        # Determine content type
        content_type = emby_response.headers.get('Content-Type', 'application/octet-stream')
        if subpath.endswith('.m3u8'):
            content_type = 'application/vnd.apple.mpegurl'
        elif subpath.endswith('.ts'):
            content_type = 'video/MP2T'

        # If this is a playlist (.m3u8), rewrite URLs
        if subpath.endswith('.m3u8'):
            playlist_content = emby_response.text

            # Add token to rewritten URLs if validation is enabled
            token_param = f"?token={request.args.get('token')}" if config.ENABLE_HLS_TOKEN_VALIDATION and request.args.get('token') else ""

            # Replace absolute Emby URLs with proxy URLs
            playlist_content = re.sub(
                rf'{re.escape(EMBY_SERVER_URL)}/emby/Videos/{item_id}/',
                f'/hls/{item_id}/',
                playlist_content
            )

            # Also handle relative URLs
            playlist_content = re.sub(
                rf'/emby/Videos/{item_id}/',
                f'/hls/{item_id}/',
                playlist_content
            )

            # Add token parameter to segment URLs if needed
            if token_param:
                # Add token to .m3u8 and .ts file references
                lines = playlist_content.split('\n')
                for i, line in enumerate(lines):
                    # Skip comment lines and empty lines
                    if line.strip().startswith('#') or not line.strip():
                        continue
                    # If line contains .m3u8 or .ts and doesn't have token already
                    if ('.m3u8' in line or '.ts' in line) and 'token=' not in line:
                        # Use & if URL already has query params, otherwise use ?
                        separator = '&' if '?' in line else '?'
                        token_to_add = f"{separator}token={request.args.get('token')}"
                        lines[i] = line + token_to_add
                playlist_content = '\n'.join(lines)

            response = Response(playlist_content, mimetype=content_type)
        else:
            def generate():
                """Generator function to stream binary video segment data in chunks."""
                for chunk in emby_response.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk

            response = Response(generate(), mimetype=content_type)

            if 'Content-Length' in emby_response.headers:
                response.headers['Content-Length'] = emby_response.headers['Content-Length']

        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Range'

        return response

    except requests.exceptions.RequestException as e:
        logger.error(f"CRITICAL: Failed to fetch HLS segment from Emby server")
        logger.error(f"  Item ID: {item_id}")
        logger.error(f"  Subpath: {subpath}")
        logger.error(f"  Emby URL: {emby_url if emby_url else '(URL not constructed)'}")
        logger.error(f"  Error: {str(e)}")
        logger.error(f"  Error Type: {type(e).__name__}")
        return jsonify({"error": "Failed to fetch video segment from media server"}), 502
    except Exception as e:
        logger.error(f"CRITICAL: Unexpected error in HLS segment proxy")
        logger.error(f"  Item ID: {item_id}")
        logger.error(f"  Subpath: {subpath}")
        logger.error(f"  Error: {str(e)}")
        logger.error(f"  Error Type: {type(e).__name__}")
        import traceback
        logger.error(f"  Traceback: {traceback.format_exc()}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/api/image/<item_id>')
def api_image(item_id):
    """
    Get poster/thumbnail image for a media item.

    Proxies image requests from Emby server to keep server internal.

    Path Parameters:
        item_id (str): Emby item ID

    Query Parameters:
        type (str, optional): Image type (default: "Primary")
            Options: "Primary", "Backdrop", "Thumb", etc.

    Returns:
        Binary image data (JPEG/PNG)

    Errors:
        404: Image not found

    Example:
        GET /api/image/12345?type=Primary
    """
    image_type = request.args.get('type', 'Primary')
    image_url = emby_client.get_image_url(item_id, image_type)

    try:
        response = requests.get(image_url, headers=emby_client.headers)
        if response.status_code == 200:
            return response.content, 200, {'Content-Type': response.headers.get('Content-Type', 'image/jpeg')}
        else:
            return '', 404
    except Exception as e:
        logger.error(f"Error fetching image: {e}")
        return '', 404

@app.route('/api/subtitles/<item_id>/<media_source_id>/<int:subtitle_index>')
def api_subtitles(item_id, media_source_id, subtitle_index):
    """
    Get subtitle file for a media item in WebVTT format.

    Proxies subtitle requests from Emby server to keep server internal.

    Path Parameters:
        item_id (str): Emby item ID
        media_source_id (str): Media source ID
        subtitle_index (int): Subtitle stream index

    Returns:
        WebVTT subtitle file (text/vtt)

    Errors:
        404: Subtitle not found

    Example:
        GET /api/subtitles/12345/67890/2
    """
    try:
        # Build Emby subtitle URL (always request VTT format for web compatibility)
        subtitle_url = f"{EMBY_SERVER_URL}/emby/Videos/{item_id}/{media_source_id}/Subtitles/{subtitle_index}/Stream.vtt"

        # Add API key
        subtitle_url += f"?api_key={EMBY_API_KEY}"

        logger.debug(f"Fetching subtitle: {subtitle_url}")

        response = requests.get(subtitle_url, headers=emby_client.headers)
        if response.status_code == 200:
            return response.content, 200, {
                'Content-Type': 'text/vtt',
                'Access-Control-Allow-Origin': '*'
            }
        else:
            logger.warning(f"Subtitle not found: {subtitle_url} (status: {response.status_code})")
            return '', 404
    except Exception as e:
        logger.error(f"Error fetching subtitle: {e}")
        return '', 404

@app.route('/api/party/create', methods=['POST'])
def create_party():
    """
    Create a new watch party room.

    Method: POST

    Returns:
        JSON: {
            "party_id": str (unique party identifier),
            "url": str (party URL path)
        }

    Rate Limit:
        5 per hour per IP (if rate limiting enabled)

    Example:
        POST /api/party/create
        Response: {"party_id": "A3B7K", "url": "/party/A3B7K"}
    """
    party_id = generate_party_code()

    watch_parties[party_id] = {
        'id': party_id,
        'created_at': datetime.now().isoformat(),
        'users': {},
        'current_video': None,
        'playback_state': {
            'playing': False,
            'time': 0,
            'last_update': datetime.now().isoformat()
        }
    }

    return jsonify({
        'party_id': party_id,
        'url': f'/party/{party_id}'
    })

# Apply rate limiting to party creation if enabled
if limiter:
    create_party = limiter.limit(config.RATE_LIMIT_PARTY_CREATION)(create_party)

@app.route('/api/party/<party_id>/info')
def party_info(party_id):
    """
    Get current state and information about a watch party.

    Path Parameters:
        party_id (str): Party ID

    Returns:
        JSON: {
            "id": str,
            "users": [str] (list of usernames),
            "current_video": {
                "item_id": str,
                "title": str,
                "overview": str,
                "stream_url_base": str,
                "audio_index": int,
                "subtitle_index": int
            } or null,
            "playback_state": {
                "playing": bool,
                "time": float,
                "last_update": str (ISO timestamp)
            }
        }

    Errors:
        404: Party not found

    Example:
        GET /api/party/abc123/info
    """
    if party_id not in watch_parties:
        return jsonify({"error": "Party not found"}), 404

    party = watch_parties[party_id]
    return jsonify({
        'id': party['id'],
        'users': list(party['users'].values()),
        'current_video': party['current_video'],
        'playback_state': party['playback_state']
    })


# =============================================================================
# WebSocket Events
# =============================================================================
"""
Socket.IO events for real-time party synchronization.

Connection Events:
    connect              - Client connects to server
    disconnect           - Client disconnects

Party Management Events:
    join_party           - Join a watch party room
        Data: {party_id, username}
    leave_party          - Leave a watch party room
        Data: {party_id}

Video Control Events (Synced to all users):
    select_video         - Select a video to watch
        Data: {party_id, item_id, item_name, item_overview}
    play                 - Play video
        Data: {party_id, time}
    pause                - Pause video
        Data: {party_id, time}
    seek                 - Seek to position
        Data: {party_id, time, playing}
    change_streams       - Change audio/subtitle tracks
        Data: {party_id, audio_index, subtitle_index}

Chat Events:
    chat_message         - Send chat message
        Data: {party_id, message}

Server Emitted Events:
    connected            - Connection confirmed
    user_joined          - User joined party
    user_left            - User left party
    sync_state           - Initial party state on join
    video_selected       - New video selected
    streams_changed      - Audio/subtitle changed
    play                 - Play command
    pause                - Pause command
    seek                 - Seek command
    chat_message         - Chat message broadcast
    error                - Error message
"""

@socketio.on('connect')
def handle_connect():
    """Handle new WebSocket connection"""
    logger.info(f"Client connected: {request.sid}")
    emit('connected', {'sid': request.sid})


@socketio.on('disconnect')
def handle_disconnect():
    """Handle WebSocket disconnection"""
    logger.info(f"Client disconnected: {request.sid}")

    # Remove user from all watch parties
    for party_id, party in watch_parties.items():
        if request.sid in party['users']:
            username = party['users'][request.sid]
            del party['users'][request.sid]
            emit('user_left', {'username': username}, room=party_id, skip_sid=request.sid)


@socketio.on('join_party')
def handle_join_party(data):
    """User joins a watch party"""
    party_id = data.get('party_id', '').strip().upper()  # Convert to uppercase for case-insensitive matching
    username = data.get('username', '').strip()

    # Generate random username if empty
    if not username:
        username = generate_random_username()
        logger.info(f"Generated random username: {username}")

    if party_id not in watch_parties:
        emit('error', {'message': 'Watch party not found'})
        return

    # Check max users per party limit
    if config.MAX_USERS_PER_PARTY > 0:
        current_user_count = len(watch_parties[party_id]['users'])
        if current_user_count >= config.MAX_USERS_PER_PARTY:
            logger.warning(f"Party {party_id} is full ({current_user_count}/{config.MAX_USERS_PER_PARTY})")
            emit('error', {'message': f'Party is full (max {config.MAX_USERS_PER_PARTY} users)'})
            return

    # Join the room
    join_room(party_id)

    # Add user to party
    watch_parties[party_id]['users'][request.sid] = username

    # Notify everyone
    emit('user_joined', {
        'username': username,
        'users': list(watch_parties[party_id]['users'].values())
    }, room=party_id)

    # Send current state to the new user with their individual token
    party = watch_parties[party_id]
    current_video = None

    if party['current_video']:
        # Build video object with individual token for this user
        current_video = {
            'item_id': party['current_video']['item_id'],
            'title': party['current_video']['title'],
            'overview': party['current_video']['overview'],
            'audio_index': party['current_video']['audio_index'],
            'subtitle_index': party['current_video']['subtitle_index'],
            'media_source_id': party['current_video'].get('media_source_id')
        }

        # Add stream URL with individual token
        stream_url = party['current_video']['stream_url_base']
        if config.ENABLE_HLS_TOKEN_VALIDATION:
            user_token = get_user_token(party_id, request.sid)
            if user_token:
                stream_url += f"&token={user_token}"
                logger.debug(f"New user {username} joining party {party_id} with token: {user_token[:16]}...")
            else:
                logger.warning(f"Failed to generate token for new user {username} in party {party_id}")

        current_video['stream_url'] = stream_url

    # Calculate accurate current time for new joiner
    playback_state = party['playback_state'].copy()
    if playback_state.get('playing') and playback_state.get('last_update'):
        try:
            # Calculate elapsed time since last update
            from datetime import datetime
            last_update = datetime.fromisoformat(playback_state['last_update'])
            elapsed_seconds = (datetime.now() - last_update).total_seconds()

            # Add elapsed time to stored time for accurate sync
            stored_time = playback_state['time']
            current_time = stored_time + elapsed_seconds
            playback_state['time'] = current_time

            logger.debug(f"New joiner sync: stored_time={stored_time:.2f}s, elapsed={elapsed_seconds:.2f}s, current_time={current_time:.2f}s")
        except Exception as e:
            logger.warning(f"Error calculating playback time for new joiner: {e}")

    emit('sync_state', {
        'current_video': current_video,
        'playback_state': playback_state
    })


@socketio.on('leave_party')
def handle_leave_party(data):
    """User leaves a watch party"""
    party_id = data.get('party_id', '').strip().upper()  # Convert to uppercase for case-insensitive matching

    if party_id in watch_parties and request.sid in watch_parties[party_id]['users']:
        username = watch_parties[party_id]['users'][request.sid]
        leave_room(party_id)
        del watch_parties[party_id]['users'][request.sid]

        emit('user_left', {
            'username': username,
            'users': list(watch_parties[party_id]['users'].values())
        }, room=party_id)


@socketio.on('select_video')
def handle_select_video(data):
    """Host selects a video to watch"""
    party_id = data.get('party_id', '').strip().upper()  # Convert to uppercase for case-insensitive matching
    item_id = data.get('item_id')
    item_name = data.get('item_name', 'Unknown')
    item_overview = data.get('item_overview', '')
    audio_index = data.get('audio_index')
    subtitle_index = data.get('subtitle_index')

    if party_id not in watch_parties:
        emit('error', {'message': 'Watch party not found'})
        return

    # Get PlaybackInfo to get MediaSourceId and PlaySessionId
    playback_info = emby_client.get_playback_info(item_id)

    if playback_info and 'MediaSources' in playback_info:
        media_source_id = playback_info['MediaSources'][0]['Id']
        play_session_id = playback_info.get('PlaySessionId')
        media_source = playback_info['MediaSources'][0]

        # If no audio/subtitle specified, use defaults from media source
        if audio_index is None and 'MediaStreams' in media_source:
            # First, try to find the default audio stream
            for stream in media_source['MediaStreams']:
                if stream.get('Type') == 'Audio' and stream.get('IsDefault'):
                    audio_index = stream.get('Index')
                    logger.debug(f"Using default audio track: {audio_index}")
                    break

            # If no default found, use the first audio stream
            if audio_index is None:
                for stream in media_source['MediaStreams']:
                    if stream.get('Type') == 'Audio':
                        audio_index = stream.get('Index')
                        logger.debug(f"No default audio found, using first audio track: {audio_index}")
                        break

        # Don't auto-select default subtitles - let users opt-in
        # (Removed automatic default subtitle selection)

        # Build direct Emby HLS URL with authentication
        params = [
            f"MediaSourceId={media_source_id}",
            f"PlaySessionId={play_session_id}",
            f"DeviceId={emby_client.device_id}",
            f"api_key={emby_client.api_key}",
            "SegmentContainer=ts",
            "TranscodingMaxAudioChannels=2",  # Ensure audio is included
            "AudioCodec=aac,mp3",  # Support AAC and MP3 for better compatibility (handles TrueHD, FLAC, etc.)
            "BreakOnNonKeyFrames=True",  # Allow seeking to any point
            "VideoCodec=h264",  # Force H.264 for maximum browser compatibility
            "MaxAudioChannels=2"  # Downmix to stereo for TrueHD/multi-channel audio
        ]

        # Add audio stream index to select specific audio track
        # This is important for videos with multiple audio tracks (different languages)
        if audio_index is not None:
            params.append(f"AudioStreamIndex={audio_index}")
            logger.debug(f"Using audio stream index: {audio_index}")
        else:
            logger.debug("No audio stream index specified, Emby will use default")

        # Handle subtitle burning based on subtitle type
        if subtitle_index is not None and subtitle_index != -1:
            # Check if this is a PGS/image-based subtitle that needs burn-in
            is_pgs = False
            for stream in media_source['MediaStreams']:
                if stream.get('Type') == 'Subtitle' and stream.get('Index') == subtitle_index:
                    codec = stream.get('Codec', '').lower()
                    is_pgs = codec in ['pgssub', 'pgs', 'dvd_subtitle', 'dvdsub', 'vobsub']
                    break

            if is_pgs:
                # Burn-in PGS subtitles for perfect quality (image-based)
                params.append(f"SubtitleStreamIndex={subtitle_index}")
                params.append("SubtitleMethod=Encode")  # Force burn-in
                logger.debug(f"Burning in PGS subtitle track {subtitle_index}")
            else:
                # Text-based subtitles: load separately as VTT for better control
                # Don't add SubtitleStreamIndex parameter - let Emby ignore subtitles
                logger.debug(f"Text subtitle {subtitle_index} will be loaded separately as VTT (not burning)")
        else:
            # No subtitles selected - don't add any subtitle parameters
            # This prevents Emby from auto-selecting default/forced subtitles
            logger.debug("No subtitles selected - omitting subtitle parameters")

        # Use Flask proxy URL to keep Emby internal (WITHOUT token)
        stream_url_base = f"/hls/{item_id}/master.m3u8?{'&'.join(params)}"
    else:
        logger.error(f"Could not get playback info for item {item_id}")
        emit('error', {'message': 'Failed to load video'})
        return

    # Stop any active transcoding for previous video (if changing videos)
    if watch_parties[party_id].get('current_video'):
        emby_client.stop_active_encodings()

    # Store base URL without token in party data
    watch_parties[party_id]['current_video'] = {
        'item_id': item_id,
        'title': item_name,
        'overview': item_overview,
        'stream_url_base': stream_url_base,  # Base URL without token
        'audio_index': audio_index,
        'subtitle_index': subtitle_index,
        'media_source_id': media_source_id,  # Needed for subtitle URLs
        'selected_by': request.sid  # Track who selected this video
    }

    watch_parties[party_id]['playback_state'] = {
        'playing': False,
        'time': 0,
        'last_update': datetime.now().isoformat()
    }

    # Send video to each user with their own individual token
    logger.debug(f"Sending video to {len(watch_parties[party_id]['users'])} users in party {party_id}")
    for user_sid in watch_parties[party_id]['users'].keys():
        username = watch_parties[party_id]['users'][user_sid]
        stream_url_with_token = stream_url_base

        # Add individual token for this user
        if config.ENABLE_HLS_TOKEN_VALIDATION:
            user_token = get_user_token(party_id, user_sid)
            if user_token:
                stream_url_with_token += f"&token={user_token}"
                logger.debug(f"Assigned token {user_token[:16]}... to user {username} (sid={user_sid})")
            else:
                logger.warning(f"Failed to get token for user {username} (sid={user_sid})")
        else:
            logger.debug(f"Sending video to user {username} without token (validation disabled)")

        logger.debug(f"Stream URL for {username}: {stream_url_with_token[:100]}...")

        # Send to this specific user with their token
        socketio.emit('video_selected', {
            'video': {
                'item_id': item_id,
                'title': item_name,
                'overview': item_overview,
                'stream_url': stream_url_with_token,  # With individual token
                'audio_index': audio_index,
                'subtitle_index': subtitle_index,
                'media_source_id': media_source_id  # Needed for subtitle URLs
            }
        }, to=user_sid)  # Send only to this user's socket


@socketio.on('stop_video')
def handle_stop_video(data):
    """
    Stop the currently playing video and clear it from the party.
    Only the user who selected the video can stop it.

    Args:
        data: {
            'party_id': str - The party ID
        }

    Emits:
        'video_stopped': Broadcast to all users in the party
        'error': If user is not authorized or party doesn't exist
    """
    party_id = data.get('party_id', '').strip().upper()  # Convert to uppercase for case-insensitive matching

    if not party_id or party_id not in watch_parties:
        emit('error', {'message': 'Party not found'})
        return

    party = watch_parties[party_id]

    # Check if there's a current video
    if not party.get('current_video'):
        emit('error', {'message': 'No video is currently playing'})
        return

    # Check if the requester is the one who selected the video
    if party['current_video'].get('selected_by') != request.sid:
        emit('error', {'message': 'Only the user who selected the video can stop it'})
        logger.warning(f"User {request.sid} tried to stop video in party {party_id} but was not authorized")
        return

    # Clear the video and reset playback state
    video_title = party['current_video'].get('title', 'Unknown')
    username = party['users'].get(request.sid, 'Unknown')

    # Stop any active transcoding sessions on Emby server
    emby_client.stop_active_encodings()

    party['current_video'] = None
    party['playback_state'] = {
        'playing': False,
        'time': 0,
        'last_update': datetime.now().isoformat()
    }

    # Broadcast to all users in the party
    emit('video_stopped', {
        'message': f'{username} stopped the video',
        'stopped_by': username
    }, room=party_id)

    logger.info(f"User {username} stopped video '{video_title}' in party {party_id}")


@socketio.on('play')
def handle_play(data):
    """Handle play command"""
    party_id = data.get('party_id', '').strip().upper()  # Convert to uppercase for case-insensitive matching
    current_time = data.get('time', 0)

    if party_id in watch_parties:
        watch_parties[party_id]['playback_state'] = {
            'playing': True,
            'time': current_time,
            'last_update': datetime.now().isoformat()
        }

        emit('play', {'time': current_time}, room=party_id, skip_sid=request.sid)


@socketio.on('pause')
def handle_pause(data):
    """Handle pause command"""
    party_id = data.get('party_id', '').strip().upper()  # Convert to uppercase for case-insensitive matching
    current_time = data.get('time', 0)

    if party_id in watch_parties:
        watch_parties[party_id]['playback_state'] = {
            'playing': False,
            'time': current_time,
            'last_update': datetime.now().isoformat()
        }

        emit('pause', {'time': current_time}, room=party_id, skip_sid=request.sid)


@socketio.on('seek')
def handle_seek(data):
    """Handle seek command with force pause for better buffering"""
    party_id = data.get('party_id', '').strip().upper()  # Convert to uppercase for case-insensitive matching
    seek_time = data.get('time', 0)

    if party_id in watch_parties:
        # Get current playing state before seek
        was_playing = watch_parties[party_id]['playback_state'].get('playing', False)

        # Update playback state
        watch_parties[party_id]['playback_state']['time'] = seek_time
        watch_parties[party_id]['playback_state']['last_update'] = datetime.now().isoformat()

        # If video was playing, force pause everyone (including seeker) for better buffering
        if was_playing:
            logger.debug(f"Seek during playback - pausing all clients (including seeker) first for buffering")
            # First, pause everyone INCLUDING the seeking client
            emit('force_pause_before_seek', {'time': seek_time}, room=party_id)

            # Then send seek command with playing flag and longer buffer delay to ALL
            emit('seek', {'time': seek_time, 'playing': True, 'buffer_delay': 1500}, room=party_id)
        else:
            # Video was already paused, just seek normally for everyone
            emit('seek', {'time': seek_time, 'playing': False}, room=party_id)

@socketio.on('change_streams')
def handle_change_streams(data):
    """Handle audio/subtitle stream changes"""
    party_id = data.get('party_id', '').strip().upper()  # Convert to uppercase for case-insensitive matching
    audio_index = data.get('audio_index')
    subtitle_index = data.get('subtitle_index')

    if party_id not in watch_parties or not watch_parties[party_id]['current_video']:
        emit('error', {'message': 'No video currently playing'})
        return

    current_video = watch_parties[party_id]['current_video']
    item_id = current_video['item_id']

    # Get PlaybackInfo for new stream parameters
    playback_info = emby_client.get_playback_info(item_id)

    if playback_info and 'MediaSources' in playback_info:
        media_source_id = playback_info['MediaSources'][0]['Id']
        play_session_id = playback_info.get('PlaySessionId')
        media_source = playback_info['MediaSources'][0]

        # Build direct Emby HLS URL with authentication
        params = [
            f"MediaSourceId={media_source_id}",
            f"PlaySessionId={play_session_id}",
            f"DeviceId={emby_client.device_id}",
            f"api_key={emby_client.api_key}",
            "SegmentContainer=ts",
            "TranscodingMaxAudioChannels=2",  # Ensure audio is included
            "AudioCodec=aac,mp3",  # Support AAC and MP3 for better compatibility (handles TrueHD, FLAC, etc.)
            "BreakOnNonKeyFrames=True",  # Allow seeking to any point
            "VideoCodec=h264",  # Force H.264 for maximum browser compatibility
            "MaxAudioChannels=2"  # Downmix to stereo for TrueHD/multi-channel audio
        ]

        # Add audio stream index to select specific audio track
        # This is important for videos with multiple audio tracks (different languages)
        if audio_index is not None:
            params.append(f"AudioStreamIndex={audio_index}")
            logger.debug(f"Using audio stream index: {audio_index}")
        else:
            logger.debug("No audio stream index specified, Emby will use default")

        # Handle subtitle burning based on subtitle type
        if subtitle_index is not None and subtitle_index != -1:
            # Check if this is a PGS/image-based subtitle that needs burn-in
            is_pgs = False
            for stream in media_source['MediaStreams']:
                if stream.get('Type') == 'Subtitle' and stream.get('Index') == subtitle_index:
                    codec = stream.get('Codec', '').lower()
                    is_pgs = codec in ['pgssub', 'pgs', 'dvd_subtitle', 'dvdsub', 'vobsub']
                    break

            if is_pgs:
                # Burn-in PGS subtitles for perfect quality (image-based)
                params.append(f"SubtitleStreamIndex={subtitle_index}")
                params.append("SubtitleMethod=Encode")  # Force burn-in
                logger.debug(f"Burning in PGS subtitle track {subtitle_index}")
            else:
                # Text-based subtitles: load separately as VTT for better control
                # Don't add SubtitleStreamIndex parameter - let Emby ignore subtitles
                logger.debug(f"Text subtitle {subtitle_index} will be loaded separately as VTT (not burning)")
        else:
            # No subtitles selected - don't add any subtitle parameters
            # This prevents Emby from auto-selecting default/forced subtitles
            logger.debug("No subtitles selected - omitting subtitle parameters")

        # Use Flask proxy URL to keep Emby internal (WITHOUT token)
        stream_url_base = f"/hls/{item_id}/master.m3u8?{'&'.join(params)}"
    else:
        logger.error(f"Could not get playback info for item {item_id}")
        emit('error', {'message': 'Failed to change streams'})
        return

    # Update the video info with base URL (no token)
    current_video['stream_url_base'] = stream_url_base
    current_video['audio_index'] = audio_index
    current_video['subtitle_index'] = subtitle_index
    current_video['media_source_id'] = media_source_id

    # Send stream change to each user with their individual token
    current_time = watch_parties[party_id]['playback_state']['time']

    for user_sid in watch_parties[party_id]['users'].keys():
        stream_url_with_token = stream_url_base

        # Add individual token for this user
        if config.ENABLE_HLS_TOKEN_VALIDATION:
            user_token = get_user_token(party_id, user_sid)
            if user_token:
                stream_url_with_token += f"&token={user_token}"

        # Send to this specific user
        socketio.emit('streams_changed', {
            'video': {
                'item_id': item_id,
                'title': current_video['title'],
                'overview': current_video['overview'],
                'stream_url': stream_url_with_token,
                'audio_index': audio_index,
                'subtitle_index': subtitle_index,
                'media_source_id': media_source_id
            },
            'current_time': current_time
        }, to=user_sid)

@socketio.on('chat_message')
def handle_chat_message(data):
    """Handle chat messages"""
    party_id = data.get('party_id', '').strip().upper()  # Convert to uppercase for case-insensitive matching
    message = data.get('message', '')

    if party_id in watch_parties and request.sid in watch_parties[party_id]['users']:
        username = watch_parties[party_id]['users'][request.sid]

        emit('chat_message', {
            'username': username,
            'message': message,
            'timestamp': datetime.now().isoformat()
        }, room=party_id)

def check_for_updates():
    """Check GitHub for latest release and notify if update available"""
    try:
        # GitHub API endpoint for latest release
        github_api_url = "https://api.github.com/repos/Oratorian/emby-watchparty/releases/latest"
        response = requests.get(github_api_url, timeout=5)

        if response.status_code == 200:
            latest_release = response.json()
            latest_version = latest_release.get('tag_name', '').lstrip('v')

            if latest_version and latest_version != VERSION:
                logger.warning("=" * 60)
                logger.warning(f"UPDATE AVAILABLE: v{latest_version} (current: v{VERSION})")
                logger.warning(f"Download: {latest_release.get('html_url', 'https://github.com/Oratorian/emby-watchparty/releases')}")
                logger.warning("=" * 60)
            else:
                logger.info(f"Running latest version: v{VERSION}")
        else:
            # Silently skip if GitHub API is unreachable
            logger.debug(f"Could not check for updates (GitHub API returned {response.status_code})")
    except Exception as e:
        # Don't spam logs if update check fails
        logger.debug(f"Update check failed: {e}")

if __name__ == '__main__':
    logger.info("=" * 60)
    logger.info("Emby Watch Party Server")
    logger.info("=" * 60)
    logger.info(f"Emby Server: {EMBY_SERVER_URL}")
    logger.info(f"API Key configured: {'Yes' if EMBY_API_KEY else 'No'}")
    logger.info("")

    # Check for updates
    check_for_updates()
    logger.info("")

    logger.info("To configure, set environment variables:")
    logger.info("  EMBY_SERVER_URL - Your Emby server URL")
    logger.info("  EMBY_API_KEY - Your Emby API key")
    logger.info("=" * 60)
    logger.info("")

    socketio.run(app, debug=False, host=config.WATCH_PARTY_BIND, port=config.WATCH_PARTY_PORT)