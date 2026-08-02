"""
SocketIO handlers for python-socketio AsyncServer
"""

from backend.src.socket_handlers.connection import register as register_connection
from backend.src.socket_handlers.party import register as register_party
from backend.src.socket_handlers.playback import register as register_playback
from backend.src.socket_handlers.sync import register as register_sync
from backend.src.socket_handlers.chat import register as register_chat
from backend.src.socket_handlers.drift import register as register_drift
from backend.src.party_lifecycle import PartyLifecycle
from backend.src.socket_protocol import install_inbound_validation, install_outbound_validation


def register_all(sio, emby_client, party_manager, token_manager, stream_builder,
                 config, logger, session_secret=None, rate_limiter=None):
    """Register all socket event handlers"""
    ctx = {
        'sio': sio,
        'emby_client': emby_client,
        'party_manager': party_manager,
        'token_manager': token_manager,
        'stream_builder': stream_builder,
        'config': config,
        'logger': logger,
        'session_secret': session_secret,
        'rate_limiter': rate_limiter,
    }
    register_connection(ctx)
    ctx['party_lifecycle'] = PartyLifecycle(ctx)
    # playback must register before party so the restart_video_from_beginning
    # helper is available in ctx for the vote-pass flow in party.py
    register_playback(ctx)
    register_party(ctx)
    register_sync(ctx)
    register_chat(ctx)
    register_drift(ctx)
    install_inbound_validation(sio, logger)
    install_outbound_validation(sio, logger)
    return ctx
