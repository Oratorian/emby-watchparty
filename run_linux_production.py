"""
Linux production entrypoint for Emby Watch Party
Uses gevent for production-ready async handling on Linux/Docker
"""

# Gevent monkey patching must be done before any other imports
from gevent import monkey
monkey.patch_all()

# Now import and run the app
from app import app, socketio, config, logger
from src.socket_handlers import check_for_updates

if __name__ == '__main__':
    logger.info("=" * 80)
    logger.info("Starting Emby Watch Party server (Production Mode)...")
    logger.info(f"Host: {config.WATCH_PARTY_BIND}")
    logger.info(f"Port: {config.WATCH_PARTY_PORT}")
    logger.info("=" * 80)

    # Check for updates (displayed at end of startup messages)
    check_for_updates(logger)

    socketio.run(
        app,
        host=config.WATCH_PARTY_BIND,
        port=int(config.WATCH_PARTY_PORT),
        debug=False
    )
