"""
Emby Watch Party - Synchronized video watching for Emby media server
Author: Oratorian
GitHub: https://github.com/Oratorian
Description: A Flask-based web application that allows multiple users to watch
             Emby media in sync with real-time chat and playback synchronization.
             Supports HLS streaming with proper authentication.

Version: 1.4.1-alpha-5 (Production Server with .env Configuration)
"""

from flask import Flask
from flask_socketio import SocketIO
import secrets
import logging
import sys

# Import rsyslog-logger (replaces custom logger)
from rsyslog_logger import setup_logger

# Import configuration
from src import config

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
app.config['PERMANENT_SESSION_LIFETIME'] = config.SESSION_EXPIRY if hasattr(config, 'SESSION_EXPIRY') else 86400

# Configure session cookie for reverse proxy deployments
# When APP_PREFIX is set (e.g., /watchparty), the session cookie must use that path
# Otherwise the cookie won't be sent with requests to the prefixed routes
if config.APP_PREFIX:
    app.config['SESSION_COOKIE_PATH'] = config.APP_PREFIX
else:
    app.config['SESSION_COOKIE_PATH'] = '/'

# SameSite=Lax allows the cookie to be sent with same-site requests and top-level navigations
# This is needed for the redirect after login to work correctly
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Setup rsyslog-logger (replaces custom logger)
# Use None for log_file when LOG_TO_FILE is false (Docker stdout-only mode)
log_file = config.LOG_FILE if config.LOG_TO_FILE == 'true' else None
logger = setup_logger(
    name="emby-watchparty",
    log_file=log_file,
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
# Reset rotation flag so each log file gets rotated independently on startup
import rsyslog_logger.logger as _rl
_rl._log_rotated = False
socketio_log_file = "logs/socketio.log" if config.LOG_TO_FILE == 'true' else None
socketio_logger = setup_logger(
    name="socketio",
    log_file=socketio_log_file,
    log_level=config.LOG_LEVEL,
    log_format=config.LOG_FORMAT,
    console_log_level=config.CONSOLE_LOG_LEVEL,
    max_size=config.LOG_MAX_SIZE,
    backup_count=5
)

# Determine Socket.IO path based on APP_PREFIX
# Always include leading slash for socket.io path (required by socket.io client)
socketio_path = f"{config.APP_PREFIX}/socket.io" if config.APP_PREFIX else "/socket.io"

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    logger=socketio_logger,
    engineio_logger=socketio_logger,
    path=socketio_path
)

# Redirect Flask/Werkzeug HTTP access logs
werkzeug_logger = logging.getLogger('werkzeug')
werkzeug_logger.handlers.clear()
_rl._log_rotated = False
access_log_file = "logs/access.log" if config.LOG_TO_FILE == 'true' else None
werkzeug_custom_logger = setup_logger(
    name="werkzeug",
    log_file=access_log_file,
    log_level=config.LOG_LEVEL,
    log_format=config.LOG_FORMAT,
    console_log_level=config.CONSOLE_LOG_LEVEL,
    max_size=config.LOG_MAX_SIZE,
    backup_count=5
)

# Initialize rate limiter if enabled
limiter = None
if config.ENABLE_RATE_LIMITING == 'true':
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
party_manager = PartyManager(
    static_party_id=config.STATIC_SESSION_ID if config.STATIC_SESSION_ENABLED == 'true' else None
)

logger.info(f"Emby Server: {config.EMBY_SERVER_URL}")
if config.APP_PREFIX:
    logger.info(f"App Prefix: {config.APP_PREFIX}")

# Create static party on startup if enabled
if config.STATIC_SESSION_ENABLED == 'true':
    from datetime import datetime
    static_id = config.STATIC_SESSION_ID
    party_manager.watch_parties[static_id] = {
        "id": static_id,
        "created_at": datetime.now().isoformat(),
        "users": {},
        "current_video": None,
        "playback_state": {
            "playing": False,
            "time": 0,
            "last_update": datetime.now().isoformat(),
        },
    }
    logger.info(f"Static session mode: {static_id}")

logger.info("Components initialized successfully")

# =============================================================================
# Template Context Processor - Inject APP_PREFIX into all templates
# =============================================================================

@app.context_processor
def inject_app_prefix():
    """Make APP_PREFIX available to all templates"""
    return {
        'app_prefix': config.APP_PREFIX,
        'socketio_path': socketio_path,
        'static_session': config.STATIC_SESSION_ENABLED == 'true',
        'static_session_id': config.STATIC_SESSION_ID if config.STATIC_SESSION_ENABLED == 'true' else None
    }

# =============================================================================
# Register Routes and Socket Handlers
# =============================================================================

logger.info("Registering routes and socket handlers...")

# Initialize all Flask HTTP routes
init_routes(app, emby_client, party_manager, config, logger, limiter)

# Initialize all SocketIO event handlers
init_socket_handlers(socketio, emby_client, party_manager, config, logger)

logger.info("Routes and handlers registered successfully")