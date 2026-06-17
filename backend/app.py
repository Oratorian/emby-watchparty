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
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from backend.src import __version__, __codename__
from backend.src.config import Config
from backend.src.log_levels import apply_log_levels
from backend.src.emby_client import EmbyClient
from backend.src.party_manager import PartyManager
from backend.src.hls_token_manager import HLSTokenManager
from backend.src.stream_builder import StreamBuilder
from backend.src.avatar_store import AvatarStore
from backend.src.update_checker import check_for_updates
from backend.src.routers import auth, library, media, hls, party, admin, avatar, health, quality
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
    # setup_logger pins the logger to LOG_LEVEL, which would gate out records
    # a more-verbose console wants. Re-apply via the shared helper so boot and
    # admin-panel changes use the same min(logger)/per-handler model.
    apply_log_levels(config)
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
    stream_builder = StreamBuilder(emby_client, logger, config)

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

# APP_PREFIX is read once at module load (this is also the moment the
# routers and mounts below are registered, before the lifespan handler
# runs). It is already rstrip('/')-cleaned by Config.from_env so an empty
# string means "serve at root" and a non-empty value always lacks a
# trailing slash. The cleanup means f"{PREFIX}/api/..." works regardless
# of whether the operator wrote `APP_PREFIX=/watchparty` or
# `APP_PREFIX=/watchparty/` in their .env.
_BOOT_CONFIG = Config.from_env()
PREFIX = _BOOT_CONFIG.APP_PREFIX

# Include API routers under the configured prefix. When PREFIX is empty,
# this evaluates to prefix="" -- the default behaviour. When PREFIX is
# `/watchparty`, every router gains that segment so `/api/auth/login`
# becomes `/watchparty/api/auth/login`. Mirrors how 1.x used a Flask
# Blueprint with `url_prefix=APP_PREFIX`.
app.include_router(auth.router, prefix=PREFIX)
app.include_router(library.router, prefix=PREFIX)
app.include_router(media.router, prefix=PREFIX)
app.include_router(hls.router, prefix=PREFIX)
app.include_router(party.router, prefix=PREFIX)
app.include_router(admin.router, prefix=PREFIX)
app.include_router(avatar.router, prefix=PREFIX)
app.include_router(health.router, prefix=PREFIX)
app.include_router(quality.router, prefix=PREFIX)

# Mount SocketIO under the same prefix so client connections that bake
# the prefix into the WebSocket URL land on the right ASGI app.
#
# Starlette's Mount preserves the full request path in scope['path']
# (it does NOT strip the mount prefix the way the docs imply), so the
# socketio sub-app sees `/partyapp/socket.io/...` even though it's
# mounted at that same path. engineio normalises its `socketio_path`
# parameter to `/<path>/` and checks that scope['path'] starts with it
# -- so we have to feed the FULL prefixed path here, not the raw
# "socket.io" segment. With APP_PREFIX empty this evaluates to
# "/socket.io", matching the historical no-proxy behaviour.
socket_app = socketio.ASGIApp(sio, socketio_path=f"{PREFIX}/socket.io")
app.mount(f"{PREFIX}/socket.io", socket_app)

# Serve Vue frontend (built files)
static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    # Static assets live under PREFIX too. With Vite's `base: './'` the
    # built index.html references assets as `./assets/...`, which the
    # browser resolves against the page URL -- if the user is on
    # `/watchparty/admin` those load from `/watchparty/assets/...`.
    app.mount(
        f"{PREFIX}/assets",
        StaticFiles(directory=str(static_dir / "assets")),
        name="assets",
    )

    def _read_index_with_prefix() -> str:
        """Read index.html and inject the runtime APP_PREFIX global
        + a `<base href>` that pins relative URL resolution to the
        SPA root.

        Two injections, both required:

        1. `<base href="${PREFIX}/">` — Vite builds with `base: './'`
           so asset URLs in index.html look like `./assets/index.js`.
           Without a `<base>` element the browser resolves those
           against the current page URL, which breaks every nested SPA
           route: on a hard refresh of `/partyapp/party/CODE` the
           browser tries to load `./assets/...` as
           `/partyapp/party/assets/...` (404, then mime-type errors as
           the SPA fallback serves HTML for the missing asset). Setting
           `<base href="/partyapp/">` makes those relative URLs always
           resolve to `/partyapp/assets/...` regardless of the current
           route depth.

        2. `<script>window.APP_PREFIX = "...";</script>` — runtime
           value the frontend reads via `src/utils/appPrefix.ts` so
           Vue Router, api/client, and the socket store all know the
           prefix without a rebuild.

        Both fall back to no-op behaviour when PREFIX is empty.
        """
        index = static_dir / "index.html"
        if not index.exists():
            return ""
        html = index.read_text(encoding="utf-8")
        # JSON-escape the script global so a stray quote in a
        # (badly-formed) APP_PREFIX cannot break out of the literal.
        import json
        # `<base href>` must end with `/` so it functions as a directory
        # and not a file path during URL resolution.
        base_href = (PREFIX or "") + "/"
        injection = (
            f'<base href="{base_href}">'
            f'<script>window.APP_PREFIX = {json.dumps(PREFIX)};</script>'
        )
        # Inject right after <head> so the <base> is the FIRST URL-
        # bearing element in <head> (before any <link>, <script>, or
        # <img> in <body>). HTML spec requires <base> appear before any
        # element with a URL attribute it would affect.
        marker = "<head>"
        if marker in html:
            return html.replace(marker, marker + injection, 1)
        return injection + html

    @app.get(PREFIX or "/", include_in_schema=False)
    async def serve_spa_root():
        """Serve the SPA at the prefix root.

        Separate from the catch-all because FastAPI's `{full_path:path}`
        pattern requires a non-empty path segment. Without this entry,
        `GET /watchparty` (no trailing slash) would 404.
        """
        if not (static_dir / "index.html").exists():
            return {"message": "Frontend not built. Run: cd frontend && npm run build"}
        return HTMLResponse(_read_index_with_prefix())

    if PREFIX:
        @app.get("/", include_in_schema=False)
        async def redirect_root_to_prefix():
            """When APP_PREFIX is set, a request to `/` is almost
            always a user who forgot the prefix. Bounce them to the
            real entry point instead of 404'ing.
            """
            return RedirectResponse(url=f"{PREFIX}/")

    @app.get(f"{PREFIX}/{{full_path:path}}", include_in_schema=False)
    async def serve_spa(full_path: str):
        """Serve Vue SPA for all non-API routes under the prefix."""
        if not (static_dir / "index.html").exists():
            return {"message": "Frontend not built. Run: cd frontend && npm run build"}
        return HTMLResponse(_read_index_with_prefix())


if __name__ == "__main__":
    # Process entrypoint (Docker CMD / bare metal). Binds to
    # WATCH_PARTY_BIND:WATCH_PARTY_PORT from the environment so the
    # documented .env knobs actually take effect. The old Docker CMD
    # invoked `uvicorn ... --port 5000` directly, which hardcoded the
    # port and silently ignored WATCH_PARTY_PORT.
    import uvicorn

    _cfg = Config.from_env()
    uvicorn.run(app, host=_cfg.WATCH_PARTY_BIND, port=_cfg.WATCH_PARTY_PORT)
