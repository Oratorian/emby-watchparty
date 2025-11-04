"""
Emby Watch Party - Synchronized video watching for Emby media server
Author: Oratorian
GitHub: https://github.com/Oratorian
Description: A Flask-based web application that allows multiple users to watch
             Emby media in sync with real-time chat and playback synchronization.
             Supports HLS streaming with proper authentication.

Version: 1.2.0 (Refactored with Modular Architecture)
"""

from flask import Flask
from flask_socketio import SocketIO
import secrets
import logging
import sys

# Import rsyslog-logger (replaces custom logger)
from rsyslog_logger import setup_logger

# Import configuration
import config

# Import our refactored modules
from src import __version__
from src.emby_client import EmbyClient
from src.party_manager import PartyManager
from src.routes import init_routes
from src.socket_handlers import init_socket_handlers

# =============================================================================
# Application Setup
# =============================================================================

app = Flask(__name__)
app.config['SECRET_KEY'] = secrets.token_hex(16)

# Setup rsyslog-logger (replaces custom logger)
logger = setup_logger(
    name="emby-watchparty",
    log_file=config.LOG_FILE,
    log_level=config.LOG_LEVEL,
    log_format=config.LOG_FORMAT,
    console_log_level=config.CONSOLE_LOG_LEVEL,
    max_size=config.LOG_MAX_SIZE,
    backup_count=5
)

logger.info(f"=" * 80)
logger.info(f"Emby Watch Party v{__version__} - Refactored Architecture")
logger.info(f"=" * 80)

# Separate logger for SocketIO/EngineIO
socketio_logger = setup_logger(
    name="socketio",
    log_file="logs/socketio.log",
    log_level=config.LOG_LEVEL,
    log_format=config.LOG_FORMAT,
    console_log_level=config.CONSOLE_LOG_LEVEL,
    max_size=config.LOG_MAX_SIZE,
    backup_count=5
)

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    logger=socketio_logger,
    engineio_logger=socketio_logger
)

# Redirect Flask/Werkzeug HTTP access logs
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.handlers.clear()
werkzeug_custom_logger = setup_logger(
    name="werkzeug",
    log_file="logs/access.log",
    log_level=config.LOG_LEVEL,
    log_format=config.LOG_FORMAT,
    console_log_level=config.CONSOLE_LOG_LEVEL,
    max_size=config.LOG_MAX_SIZE,
    backup_count=5
)

# Initialize rate limiter if enabled
limiter = None
if config.ENABLE_RATE_LIMITING:
    try:
        from flask_limiter import Limiter
        from flask_limiter.util import get_remote_address
        limiter = Limiter(
            app=app,
            key_func=get_remote_address,
            default_limits=[config.RATE_LIMIT_API_CALLS],
            storage_uri="memory://"
        )
        logger.info("Rate limiting: ENABLED")
    except ImportError:
        logger.error("ENABLE_RATE_LIMITING is set to true, but Flask-Limiter is not installed!")
        logger.error("Install with: pip install Flask-Limiter")
        sys.exit(1)
else:
    logger.info("Rate limiting: DISABLED")

# =============================================================================
# Initialize Core Components (Dependency Injection)
# =============================================================================

logger.info("Initializing components...")

# Initialize Emby client with logger injection
emby_client = EmbyClient(
    server_url=config.EMBY_SERVER_URL,
    api_key=config.EMBY_API_KEY,
    logger=logger,
    username=config.EMBY_USERNAME,
    password=config.EMBY_PASSWORD
)

# Initialize party manager
party_manager = PartyManager()

logger.info(f"Emby Server: {config.EMBY_SERVER_URL}")
logger.info("Components initialized successfully")

# =============================================================================
# Register Routes and Socket Handlers
# =============================================================================

logger.info("Registering routes and socket handlers...")

# Initialize all Flask HTTP routes
init_routes(app, emby_client, party_manager, config, logger, limiter)

# Initialize all SocketIO event handlers
init_socket_handlers(socketio, emby_client, party_manager, config, logger)

logger.info("Routes and handlers registered successfully")

# =============================================================================
# Run Application
# =============================================================================

if __name__ == '__main__':
    logger.info("=" * 80)
    logger.info("Starting Emby Watch Party server...")
    logger.info(f"Host: {config.WATCH_PARTY_BIND}")
    logger.info(f"Port: {config.WATCH_PARTY_PORT}")
    logger.info("=" * 80)

    try:
        socketio.run(
            app,
            host=config.WATCH_PARTY_BIND,
            port=config.WATCH_PARTY_PORT,
            debug=False
        )
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        raise
