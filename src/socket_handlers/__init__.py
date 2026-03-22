"""
SocketIO Handlers Package
Split into modules for maintainability. Each module registers its events on the shared socketio instance.
"""

from src.socket_handlers.connection import register as register_connection
from src.socket_handlers.party import register as register_party
from src.socket_handlers.playback import register as register_playback
from src.socket_handlers.sync import register as register_sync
from src.socket_handlers.chat import register as register_chat
from src.socket_handlers.drift import register as register_drift


def init_socket_handlers(socketio, emby_client, party_manager, config, logger,
                         token_manager=None, stream_builder=None):
    """
    Initialize all SocketIO event handlers with dependency injection.

    During the 2.0 transition, handlers still use the deps dict pattern.
    The new services (token_manager, stream_builder) are passed through
    deps for handlers that have been updated to use them.
    """
    from src.utils import generate_random_username

    # Build compatibility deps dict for old-style handlers.
    # Handlers access party state through party_manager methods now,
    # but some still reach into watch_parties dict directly during transition.
    deps = {
        'socketio': socketio,
        'emby_client': emby_client,
        'party_manager': party_manager,
        'config': config,
        'logger': logger,
        'watch_parties': party_manager.get_all(),
        # New services (available to updated handlers)
        'token_manager': token_manager,
        'stream_builder': stream_builder,
        # Utils
        'generate_random_username': generate_random_username,
    }

    # Legacy shims: handlers that still call get_user_token(party_id, sid, hls_tokens, config, logger)
    if token_manager:
        deps['hls_tokens'] = token_manager._tokens
        deps['get_user_token'] = lambda pid, sid, ht, cfg, lg: token_manager.get_or_create(pid, sid)
        deps['generate_hls_token'] = lambda pid, sid, ht, cfg, lg: token_manager.generate(pid, sid)
    else:
        # No token_manager provided -- token functions will be no-ops
        deps['hls_tokens'] = {}
        deps['generate_hls_token'] = lambda pid, sid, ht, cfg, lg: None
        deps['get_user_token'] = lambda pid, sid, ht, cfg, lg: None

    register_connection(deps)
    register_party(deps)
    register_playback(deps)
    register_sync(deps)
    register_chat(deps)
    register_drift(deps)
