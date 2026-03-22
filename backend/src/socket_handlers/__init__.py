"""
SocketIO handlers for python-socketio AsyncServer
"""

from backend.src.socket_handlers.connection import register as register_connection
from backend.src.socket_handlers.party import register as register_party
from backend.src.socket_handlers.playback import register as register_playback
from backend.src.socket_handlers.sync import register as register_sync
from backend.src.socket_handlers.chat import register as register_chat
from backend.src.socket_handlers.drift import register as register_drift


def register_all(sio, emby_client, party_manager, token_manager, stream_builder, config, logger):
    """Register all socket event handlers"""
    ctx = {
        'sio': sio,
        'emby_client': emby_client,
        'party_manager': party_manager,
        'token_manager': token_manager,
        'stream_builder': stream_builder,
        'config': config,
        'logger': logger,
    }
    register_connection(ctx)
    register_party(ctx)
    register_playback(ctx)
    register_sync(ctx)
    register_chat(ctx)
    register_drift(ctx)
