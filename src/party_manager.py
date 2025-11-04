"""
Party Manager Module
Manages watch party state and operations
"""

from datetime import datetime
from src.utils import generate_party_code


class PartyManager:
    """
    Manages watch parties and their state.

    Party structure:
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
                'subtitle_index': int,
                'media_source_id': str,
                'selected_by': str (socket_id)
            },
            'playback_state': {
                'playing': bool,
                'time': float,
                'last_update': str (ISO format)
            }
        }
    }
    """

    def __init__(self):
        """Initialize party manager with empty state"""
        self.watch_parties = {}
        self.hls_tokens = {}

    def create_party(self):
        """
        Create a new watch party with unique ID

        Returns:
            str: Party ID
        """
        party_id = generate_party_code(self.watch_parties)
        self.watch_parties[party_id] = {
            "id": party_id,
            "created_at": datetime.now().isoformat(),
            "users": {},
            "current_video": None,
            "playback_state": {
                "playing": False,
                "time": 0,
                "last_update": datetime.now().isoformat(),
            },
        }
        return party_id

    def party_exists(self, party_id):
        """Check if party exists"""
        return party_id in self.watch_parties

    def get_party(self, party_id):
        """Get party data"""
        return self.watch_parties.get(party_id)

    def add_user(self, party_id, socket_id, username):
        """Add user to party"""
        if party_id in self.watch_parties:
            self.watch_parties[party_id]["users"][socket_id] = username

    def remove_user(self, party_id, socket_id):
        """Remove user from party"""
        if party_id in self.watch_parties:
            if socket_id in self.watch_parties[party_id]["users"]:
                del self.watch_parties[party_id]["users"][socket_id]

            # Clean up empty parties
            if len(self.watch_parties[party_id]["users"]) == 0:
                del self.watch_parties[party_id]
                return True  # Party was deleted
        return False

    def get_users(self, party_id):
        """Get list of usernames in party"""
        if party_id in self.watch_parties:
            return list(self.watch_parties[party_id]["users"].values())
        return []

    def set_video(self, party_id, video_data):
        """Set current video for party"""
        if party_id in self.watch_parties:
            self.watch_parties[party_id]["current_video"] = video_data

    def get_video(self, party_id):
        """Get current video for party"""
        if party_id in self.watch_parties:
            return self.watch_parties[party_id]["current_video"]
        return None

    def clear_video(self, party_id):
        """Clear current video for party"""
        if party_id in self.watch_parties:
            self.watch_parties[party_id]["current_video"] = None

    def update_playback_state(self, party_id, playing=None, time=None):
        """Update playback state for party"""
        if party_id in self.watch_parties:
            if playing is not None:
                self.watch_parties[party_id]["playback_state"]["playing"] = playing
            if time is not None:
                self.watch_parties[party_id]["playback_state"]["time"] = time
            self.watch_parties[party_id]["playback_state"][
                "last_update"
            ] = datetime.now().isoformat()

    def get_playback_state(self, party_id):
        """Get playback state for party"""
        if party_id in self.watch_parties:
            return self.watch_parties[party_id]["playback_state"]
        return None

    def find_user_party(self, socket_id):
        """Find which party a user is in"""
        for party_id, party in self.watch_parties.items():
            if socket_id in party["users"]:
                return party_id
        return None

    def get_all_parties(self):
        """Get all parties"""
        return self.watch_parties

    def get_party_count(self):
        """Get number of active parties"""
        return len(self.watch_parties)
