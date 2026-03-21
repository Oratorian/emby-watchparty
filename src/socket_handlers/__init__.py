"""
SocketIO Handlers Package
Split into modules for maintainability. Each module registers its events on the shared socketio instance.
"""

from src.socket_handlers.updates import check_for_updates
from src.socket_handlers.connection import register as register_connection
from src.socket_handlers.party import register as register_party
from src.socket_handlers.playback import register as register_playback
from src.socket_handlers.sync import register as register_sync
from src.socket_handlers.chat import register as register_chat
from src.socket_handlers.drift import register as register_drift


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
    from src.utils import generate_random_username, generate_hls_token, get_user_token

    # Quick access to state
    watch_parties = party_manager.watch_parties
    hls_tokens = party_manager.hls_tokens

    # Shared dependencies passed to each handler module
    deps = {
        'socketio': socketio,
        'emby_client': emby_client,
        'party_manager': party_manager,
        'config': config,
        'logger': logger,
        'watch_parties': watch_parties,
        'hls_tokens': hls_tokens,
        # Utils
        'generate_random_username': generate_random_username,
        'generate_hls_token': generate_hls_token,
        'get_user_token': get_user_token,
    }

    # Register all handler modules
    register_connection(deps)
    register_party(deps)
    register_playback(deps)
    register_sync(deps)
    register_chat(deps)
    register_drift(deps)
