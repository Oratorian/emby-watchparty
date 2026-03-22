"""
Application Factory
Creates and wires all application components
"""

import logging
import secrets
import sys

from flask import Flask
from flask_socketio import SocketIO
from rsyslog_logger import setup_logger
import rsyslog_logger.logger as _rl

from src import __version__, __codename__
from src.config import Config
from src.emby_client import EmbyClient
from src.party_manager import PartyManager
from src.hls_token_manager import HLSTokenManager
from src.stream_builder import StreamBuilder
from src.update_checker import check_for_updates
from src.routes import init_routes
from src.socket_handlers import init_socket_handlers


def _setup_logging(config: Config):
    """Configure all application loggers. Returns the main logger."""
    log_file = config.LOG_FILE if config.LOG_TO_FILE else None

    logger = setup_logger(
        name="emby-watchparty",
        log_file=log_file,
        log_level=config.LOG_LEVEL,
        log_format=config.LOG_FORMAT,
        console_log_level=config.CONSOLE_LOG_LEVEL,
        max_size=config.LOG_MAX_SIZE,
        backup_count=5,
    )

    # SocketIO logger (separate log file)
    _rl._log_rotated = False
    socketio_log_file = "logs/socketio.log" if config.LOG_TO_FILE else None
    socketio_logger = setup_logger(
        name="socketio",
        log_file=socketio_log_file,
        log_level=config.LOG_LEVEL,
        log_format=config.LOG_FORMAT,
        console_log_level=config.CONSOLE_LOG_LEVEL,
        max_size=config.LOG_MAX_SIZE,
        backup_count=5,
    )

    # Werkzeug / access logger (separate log file)
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.handlers.clear()
    _rl._log_rotated = False
    access_log_file = "logs/access.log" if config.LOG_TO_FILE else None
    setup_logger(
        name="werkzeug",
        log_file=access_log_file,
        log_level=config.LOG_LEVEL,
        log_format=config.LOG_FORMAT,
        console_log_level=config.CONSOLE_LOG_LEVEL,
        max_size=config.LOG_MAX_SIZE,
        backup_count=5,
    )

    return logger, socketio_logger


def _setup_rate_limiter(app: Flask, config: Config, logger):
    """Configure Flask-Limiter if enabled. Returns limiter or None."""
    if not config.ENABLE_RATE_LIMITING:
        logger.info("Rate limiting: DISABLED")
        return None

    try:
        from flask_limiter import Limiter
        from flask_limiter.util import get_remote_address

        limiter = Limiter(
            app=app,
            key_func=get_remote_address,
            default_limits=[config.RATE_LIMIT_API_CALLS],
            storage_uri="memory://",
        )
        logger.info("Rate limiting: ENABLED")
        return limiter
    except ImportError:
        logger.error("ENABLE_RATE_LIMITING is set to true, but Flask-Limiter is not installed!")
        logger.error("Install with: pip install Flask-Limiter")
        sys.exit(1)


def create_app(config: Config = None):
    """
    Application factory. Creates and wires all components.

    Returns:
        tuple: (app, socketio, config, logger)
    """
    if config is None:
        config = Config.from_env()

    # Logging
    logger, socketio_logger = _setup_logging(config)

    logger.info("=" * 80)
    logger.info(f'Emby Watch Party v{__version__} - "{__codename__}"')
    logger.info("=" * 80)

    # Flask app
    app = Flask(__name__)
    app.config['SECRET_KEY'] = secrets.token_hex(16)
    app.config['PERMANENT_SESSION_LIFETIME'] = config.SESSION_EXPIRY
    app.config['SESSION_COOKIE_PATH'] = config.APP_PREFIX if config.APP_PREFIX else '/'
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

    # SocketIO
    socketio_path = f"{config.APP_PREFIX}/socket.io" if config.APP_PREFIX else "/socket.io"
    socketio = SocketIO(
        app,
        cors_allowed_origins="*",
        logger=socketio_logger,
        engineio_logger=socketio_logger,
        path=socketio_path,
    )

    # Rate limiter
    limiter = _setup_rate_limiter(app, config, logger)

    # Core services
    logger.info("Initializing components...")

    emby_client = EmbyClient(
        server_url=config.EMBY_SERVER_URL,
        api_key=config.EMBY_API_KEY,
        logger=logger,
        username=config.EMBY_USERNAME,
        password=config.EMBY_PASSWORD,
    )

    party_manager = PartyManager(config, logger)
    token_manager = HLSTokenManager(config, logger)
    stream_builder = StreamBuilder(emby_client, logger)

    logger.info(f"Emby Server: {config.EMBY_SERVER_URL}")
    if config.APP_PREFIX:
        logger.info(f"App Prefix: {config.APP_PREFIX}")
    logger.info("Components initialized successfully")

    # Template context
    @app.context_processor
    def inject_globals():
        return {
            'app_prefix': config.APP_PREFIX,
            'socketio_path': socketio_path,
            'static_session': config.STATIC_SESSION_ENABLED,
            'static_session_id': config.STATIC_SESSION_ID if config.STATIC_SESSION_ENABLED else None,
        }

    # Register routes and socket handlers
    logger.info("Registering routes and socket handlers...")
    init_routes(app, emby_client, party_manager, config, logger, limiter,
                token_manager=token_manager, stream_builder=stream_builder)
    init_socket_handlers(socketio, emby_client, party_manager, config, logger,
                         token_manager=token_manager, stream_builder=stream_builder)
    logger.info("Routes and handlers registered successfully")

    # Check for updates
    check_for_updates(logger)

    return app, socketio, config, logger
