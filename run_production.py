"""
Production entrypoint for Emby Watch Party
Uses gevent for production-ready async handling
"""

# Gevent monkey patching must be done before any other imports
from gevent import monkey
monkey.patch_all()

from app import app, socketio, config, logger

if __name__ == '__main__':
    logger.info("=" * 80)
    logger.info("Starting Emby Watch Party server (Production Mode)...")
    logger.info(f"Host: {config.WATCH_PARTY_BIND}")
    logger.info(f"Port: {config.WATCH_PARTY_PORT}")
    logger.info("=" * 80)

    socketio.run(
        app,
        host=config.WATCH_PARTY_BIND,
        port=config.WATCH_PARTY_PORT,
        debug=False,
    )
