"""
Emby Watch Party - Synchronized video watching for Emby media server
Author: Oratorian
GitHub: https://github.com/Oratorian

Single entrypoint for the application.
"""

# Gevent monkey patching must be done before any other imports
from gevent import monkey
monkey.patch_all()

from src.app_factory import create_app

app, socketio, config, logger = create_app()

if __name__ == '__main__':
    logger.info("=" * 80)
    logger.info("Starting Emby Watch Party server...")
    logger.info(f"Host: {config.WATCH_PARTY_BIND}")
    logger.info(f"Port: {config.WATCH_PARTY_PORT}")
    logger.info("=" * 80)

    socketio.run(
        app,
        host=config.WATCH_PARTY_BIND,
        port=config.WATCH_PARTY_PORT,
        debug=False,
    )
