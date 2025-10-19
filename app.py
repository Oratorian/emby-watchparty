"""
Emby Watch Party - Synchronized video watching for Emby media server
Author: Oratorian
GitHub: https://github.com/Oratorian
Description: A Flask-based web application that allows multiple users to watch
             Emby media in sync with real-time chat and playback synchronization.
             Supports HLS streaming with proper authentication.
Version: 1.0.1
"""

from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room, rooms
import requests
from datetime import datetime
import secrets
import random
import os
import sys

# Add logger directory to path and import logger
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'logger'))
from logger import setup_logger
import config

# Import config values
EMBY_SERVER_URL = config.EMBY_SERVER_URL
EMBY_API_KEY = config.EMBY_API_KEY
EMBY_USERNAME = config.EMBY_USERNAME
EMBY_PASSWORD = config.EMBY_PASSWORD

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(16)
socketio = SocketIO(app, cors_allowed_origins="*")

# Initialize logger
logger = setup_logger("emby-watchparty")

# Store active watch party rooms
watch_parties = {}

# Random username generator
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


class EmbyClient:
    """Client for interacting with Emby Server API"""

    def __init__(self, server_url, api_key, username=None, password=None):
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


# Initialize Emby client with user authentication
emby_client = EmbyClient(EMBY_SERVER_URL, EMBY_API_KEY, EMBY_USERNAME, EMBY_PASSWORD)


# ============== Web Routes ==============

@app.route('/')
def index():
    """Main page - choose to create or join a watch party"""
    return render_template('index.html')


@app.route('/party/<party_id>')
def party(party_id):
    """Watch party room page"""
    if party_id not in watch_parties:
        return render_template('error.html',
                             party_id=party_id,
                             message="The watch party you're looking for doesn't exist or has ended."), 404
    return render_template('party.html', party_id=party_id)


# ============== API Routes ==============

@app.route('/api/libraries')
def api_libraries():
    """Get all media libraries"""
    libraries = emby_client.get_libraries()
    return jsonify(libraries)


@app.route('/api/items')
def api_items():
    """Get items from a library"""
    parent_id = request.args.get('parentId')
    item_type = request.args.get('type')
    recursive = request.args.get('recursive', 'false').lower() == 'true'

    items = emby_client.get_items(parent_id, item_type, recursive)
    return jsonify(items)


@app.route('/api/item/<item_id>')
def api_item_details(item_id):
    """Get details for a specific item"""
    details = emby_client.get_item_details(item_id)
    if details:
        return jsonify(details)
    return jsonify({"error": "Item not found"}), 404


@app.route('/api/item/<item_id>/streams')
def api_item_streams(item_id):
    """Get available audio and subtitle streams for an item"""
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

    # Extract media streams - could be at different locations depending on endpoint
    media_streams = []

    # Check if we got PlaybackInfo response
    if 'MediaSources' in playback_info and playback_info['MediaSources']:
        media_streams = playback_info['MediaSources'][0].get('MediaStreams', [])
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
                'title': stream.get('Title', '')
            })

    logger.debug(f"Processed {len(audio_streams)} audio streams and {len(subtitle_streams)} subtitle streams")

    return jsonify({
        'audio': audio_streams,
        'subtitles': subtitle_streams
    })




@app.route('/hls/<item_id>/master.m3u8')
def proxy_hls_master(item_id):
    """Lightweight HLS master playlist proxy - keeps Emby internal"""
    try:
        from flask import Response
        import re

        # Forward all query parameters from client
        query_string = request.query_string.decode('utf-8')

        # Build Emby URL
        emby_url = f"{EMBY_SERVER_URL}/emby/Videos/{item_id}/master.m3u8"
        if query_string:
            emby_url += f"?{query_string}"

        logger.debug(f"Proxying HLS master: {emby_url}")

        # Fetch from Emby (internal network only)
        emby_response = requests.get(emby_url, headers=emby_client.headers)
        emby_response.raise_for_status()

        # Rewrite URLs in the playlist to point to our proxy
        playlist_content = emby_response.text

        # Replace absolute Emby URLs with proxy URLs
        # Pattern: http://server/emby/Videos/ITEMID/path → /hls/ITEMID/path
        playlist_content = re.sub(
            rf'{re.escape(EMBY_SERVER_URL)}/emby/Videos/{item_id}/',
            f'/hls/{item_id}/',
            playlist_content
        )

        # Also handle relative URLs that might start with just the path
        # Pattern: /emby/Videos/ITEMID/path → /hls/ITEMID/path
        playlist_content = re.sub(
            rf'/emby/Videos/{item_id}/',
            f'/hls/{item_id}/',
            playlist_content
        )

        logger.debug(f"Rewritten playlist URLs to use /hls/{item_id}/ prefix")

        # Return with CORS headers
        response = Response(playlist_content, mimetype='application/vnd.apple.mpegurl')
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Methods'] = 'GET, OPTIONS'
        response.headers['Access-Control-Allow-Headers'] = 'Range'

        return response

    except Exception as e:
        logger.error(f"Error proxying HLS master: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/hls/<item_id>/<path:subpath>')
def proxy_hls_segment(item_id, subpath):
    """Lightweight HLS segment/playlist proxy - keeps Emby internal"""
    try:
        from flask import Response
        import re

        # Forward all query parameters
        query_string = request.query_string.decode('utf-8')

        emby_url = f"{EMBY_SERVER_URL}/emby/Videos/{item_id}/{subpath}"
        if query_string:
            emby_url += f"?{query_string}"

        logger.debug(f"Proxying HLS segment: {subpath}")

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

            response = Response(playlist_content, mimetype=content_type)
        else:
            # For binary content (.ts files), stream as-is
            def generate():
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

    except Exception as e:
        logger.error(f"Error proxying HLS segment {subpath}: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/image/<item_id>')
def api_image(item_id):
    """Proxy image requests to Emby server"""
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


@app.route('/api/party/create', methods=['POST'])
def create_party():
    """Create a new watch party"""
    party_id = secrets.token_urlsafe(8)

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


@app.route('/api/party/<party_id>/info')
def party_info(party_id):
    """Get information about a watch party"""
    if party_id not in watch_parties:
        return jsonify({"error": "Party not found"}), 404

    party = watch_parties[party_id]
    return jsonify({
        'id': party['id'],
        'users': list(party['users'].values()),
        'current_video': party['current_video'],
        'playback_state': party['playback_state']
    })


# ============== WebSocket Events ==============

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
    party_id = data.get('party_id')
    username = data.get('username', '').strip()

    # Generate random username if empty
    if not username:
        username = generate_random_username()
        logger.info(f"Generated random username: {username}")

    if party_id not in watch_parties:
        emit('error', {'message': 'Watch party not found'})
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

    # Send current state to the new user
    party = watch_parties[party_id]
    emit('sync_state', {
        'current_video': party['current_video'],
        'playback_state': party['playback_state']
    })


@socketio.on('leave_party')
def handle_leave_party(data):
    """User leaves a watch party"""
    party_id = data.get('party_id')

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
    party_id = data.get('party_id')
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
            for stream in media_source['MediaStreams']:
                if stream.get('Type') == 'Audio' and stream.get('IsDefault'):
                    audio_index = stream.get('Index')
                    logger.debug(f"Using default audio track: {audio_index}")
                    break

        if subtitle_index is None and 'MediaStreams' in media_source:
            for stream in media_source['MediaStreams']:
                if stream.get('Type') == 'Subtitle' and stream.get('IsDefault'):
                    subtitle_index = stream.get('Index')
                    logger.debug(f"Using default subtitle track: {subtitle_index}")
                    break

        # Build direct Emby HLS URL with authentication
        params = [
            f"MediaSourceId={media_source_id}",
            f"PlaySessionId={play_session_id}",
            f"DeviceId={emby_client.device_id}",
            f"api_key={emby_client.api_key}",
            "VideoCodec=h264",
            "AudioCodec=aac",
            "MaxAudioChannels=2",
            "SegmentContainer=ts"
        ]

        if audio_index is not None:
            params.append(f"AudioStreamIndex={audio_index}")
        if subtitle_index is not None and subtitle_index != -1:
            params.append(f"SubtitleStreamIndex={subtitle_index}")
            params.append("SubtitleMethod=Encode")  # Burn subtitles into video

        # Use Flask proxy URL to keep Emby internal
        stream_url = f"/hls/{item_id}/master.m3u8?{'&'.join(params)}"
    else:
        logger.error(f"Could not get playback info for item {item_id}")
        emit('error', {'message': 'Failed to load video'})
        return

    watch_parties[party_id]['current_video'] = {
        'item_id': item_id,
        'title': item_name,
        'overview': item_overview,
        'stream_url': stream_url,
        'audio_index': audio_index,
        'subtitle_index': subtitle_index
    }

    watch_parties[party_id]['playback_state'] = {
        'playing': False,
        'time': 0,
        'last_update': datetime.now().isoformat()
    }

    # Broadcast to all users in the party
    emit('video_selected', {
        'video': watch_parties[party_id]['current_video']
    }, room=party_id)


@socketio.on('play')
def handle_play(data):
    """Handle play command"""
    party_id = data.get('party_id')
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
    party_id = data.get('party_id')
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
    party_id = data.get('party_id')
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
    party_id = data.get('party_id')
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

        # Build direct Emby HLS URL with authentication
        params = [
            f"MediaSourceId={media_source_id}",
            f"PlaySessionId={play_session_id}",
            f"DeviceId={emby_client.device_id}",
            f"api_key={emby_client.api_key}",
            "VideoCodec=h264",
            "AudioCodec=aac",
            "MaxAudioChannels=2",
            "SegmentContainer=ts"
        ]

        if audio_index is not None:
            params.append(f"AudioStreamIndex={audio_index}")
        if subtitle_index is not None and subtitle_index != -1:
            params.append(f"SubtitleStreamIndex={subtitle_index}")
            params.append("SubtitleMethod=Encode")  # Burn subtitles into video

        # Use Flask proxy URL to keep Emby internal
        stream_url = f"/hls/{item_id}/master.m3u8?{'&'.join(params)}"
    else:
        logger.error(f"Could not get playback info for item {item_id}")
        emit('error', {'message': 'Failed to change streams'})
        return

    # Update the video info
    current_video['stream_url'] = stream_url
    current_video['audio_index'] = audio_index
    current_video['subtitle_index'] = subtitle_index

    # Broadcast stream change to all users
    emit('streams_changed', {
        'video': current_video,
        'current_time': watch_parties[party_id]['playback_state']['time']
    }, room=party_id)


@socketio.on('chat_message')
def handle_chat_message(data):
    """Handle chat messages"""
    party_id = data.get('party_id')
    message = data.get('message', '')

    if party_id in watch_parties and request.sid in watch_parties[party_id]['users']:
        username = watch_parties[party_id]['users'][request.sid]

        emit('chat_message', {
            'username': username,
            'message': message,
            'timestamp': datetime.now().isoformat()
        }, room=party_id)


if __name__ == '__main__':
    logger.info("=" * 60)
    logger.info("Emby Watch Party Server")
    logger.info("=" * 60)
    logger.info(f"Emby Server: {EMBY_SERVER_URL}")
    logger.info(f"API Key configured: {'Yes' if EMBY_API_KEY else 'No'}")
    logger.info("")
    logger.info("To configure, set environment variables:")
    logger.info("  EMBY_SERVER_URL - Your Emby server URL")
    logger.info("  EMBY_API_KEY - Your Emby API key")
    logger.info("=" * 60)
    logger.info("")

    socketio.run(app, debug=True, host='0.0.0.0', port=5000)
