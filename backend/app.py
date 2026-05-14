"""
Emby Watch Party 2.0 - FastAPI + python-socketio backend
"""

import secrets
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import socketio
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.middleware.sessions import SessionMiddleware

from backend.src import __version__, __codename__
from backend.src.config import Config
from backend.src.emby_client import EmbyClient
from backend.src.party_manager import PartyManager
from backend.src.hls_token_manager import HLSTokenManager
from backend.src.stream_builder import StreamBuilder
from backend.src.avatar_store import AvatarStore
from backend.src.update_checker import check_for_updates
from backend.src.routers import auth, library, media, hls, party, admin, avatar
from backend.src.socket_handlers import register_all as register_socket_handlers


def _setup_logging(config: Config):
    """Set up application logger"""
    from rsyslog_logger import setup_logger

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
    return logger


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown"""
    config = Config.from_env()
    logger = _setup_logging(config)

    logger.info("=" * 80)
    logger.info(f'Emby Watch Party v{__version__} - "{__codename__}"')
    logger.info("=" * 80)

    logger.info("Initializing components...")

    emby_client = EmbyClient(
        server_url=config.EMBY_SERVER_URL,
        api_key=config.EMBY_API_KEY,
        logger=logger,
    )

    party_manager = PartyManager(config, logger)
    token_manager = HLSTokenManager(config, logger)
    stream_builder = StreamBuilder(emby_client, logger)

    # Avatar storage lives alongside config.json. The images directory
    # is a sibling so Docker mounts can target it explicitly.
    project_root = Path(__file__).parent.parent
    avatar_store = AvatarStore(
        db_path=project_root / "data" / "avatars.db",
        avatars_dir=project_root / "images" / "avatars",
        logger=logger,
    )

    logger.info(f"Emby Server: {config.EMBY_SERVER_URL}")
    if config.APP_PREFIX:
        logger.info(f"App Prefix: {config.APP_PREFIX}")
    logger.info("Components initialized successfully")

    # Store on app.state for dependency injection
    app.state.config = config
    app.state.logger = logger
    app.state.emby_client = emby_client
    app.state.party_manager = party_manager
    app.state.token_manager = token_manager
    app.state.stream_builder = stream_builder
    app.state.avatar_store = avatar_store
    app.state.sio = sio
    app.state.session_secret = SESSION_SECRET

    # Register socket handlers
    register_socket_handlers(
        sio, emby_client, party_manager, token_manager,
        stream_builder, config, logger,
        session_secret=SESSION_SECRET,
    )
    logger.info("Socket handlers registered")

    check_for_updates(logger)

    yield

    logger.info("Shutting down...")


# Create SocketIO server
sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')

# Create FastAPI app
app = FastAPI(
    title="Emby Watch Party",
    version=__version__,
    description="Synchronized video watching for Emby media servers",
    lifespan=lifespan,
)

# Session middleware. Secret is reused by the socket connect handler to
# decode the same cookie, so we generate it once and stash it on app.state
# (see lifespan above for the assignment).
SESSION_SECRET = secrets.token_hex(32)
app.add_middleware(SessionMiddleware, secret_key=SESSION_SECRET)

# Include API routers
app.include_router(auth.router)
app.include_router(library.router)
app.include_router(media.router)
app.include_router(hls.router)
app.include_router(party.router)
app.include_router(admin.router)
app.include_router(avatar.router)

# Mount SocketIO
socket_app = socketio.ASGIApp(sio, socketio_path="socket.io")
app.mount("/socket.io", socket_app)

# Serve Vue frontend (built files)
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """Serve Vue SPA for all non-API routes"""
        index = static_dir / "index.html"
        if index.exists():
            return FileResponse(str(index))
        return {"message": "Frontend not built. Run: cd frontend && npm run build"}
