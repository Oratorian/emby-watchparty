"""
SocketIO Event Handlers Module
All WebSocket event handlers for real-time communication
"""

from flask_socketio import emit, join_room, leave_room, rooms
from flask import request
from datetime import datetime
import time


def init_socket_handlers(socketio, emby_client, party_manager, config, logger):
    """
    Initialize all SocketIO event handlers with dependency injection
    
    Args:
        socketio: SocketIO instance
        emby_client: EmbyClient instance
        party_manager: PartyManager instance
        config: Configuration module
        logger: Logger instance
    """
    
    # Import utils functions
    from src.utils import (
        generate_random_username,
        generate_hls_token,
        get_user_token
    )
    
    # Quick access to state
    watch_parties = party_manager.watch_parties
    hls_tokens = party_manager.hls_tokens
    
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
                emit('user_left', {
                    'username': username,
                    'users': list(party['users'].values())
                }, room=party_id, skip_sid=request.sid)


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
                user_token = get_user_token(party_id, request.sid, hls_tokens, config, logger)
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
                user_token = get_user_token(party_id, user_sid, hls_tokens, config, logger)
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
                user_token = get_user_token(party_id, user_sid, hls_tokens, config, logger)
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

    @socketio.on('video_ended')
    def handle_video_ended(data):
        """Handle video ended notification"""
        party_id = data.get('party_id', '').strip().upper()

        if party_id in watch_parties:
            logger.info(f"Video ended in party {party_id}")

            # Reset playback state to prevent position carry-over to next video
            watch_parties[party_id]['playback_state'] = {
                'playing': False,
                'time': 0,
                'last_update': datetime.now().isoformat()
            }

            # Broadcast to all users in the party
            emit('video_ended', {
                'party_id': party_id,
                'timestamp': datetime.now().isoformat()
            }, room=party_id)

    @socketio.on('toggle_library')
    def handle_toggle_library(data):
        """Handle library sidebar toggle for all users"""
        party_id = data.get('party_id', '').strip().upper()
        show = data.get('show', False)

        if party_id in watch_parties:
            logger.info(f"Library toggled in party {party_id}: show={show}")

            # Broadcast to all users in the party
            emit('toggle_library', {
                'show': show
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
