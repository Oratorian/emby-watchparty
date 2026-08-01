"""
Emby Watch Party 2.0 - FastAPI + python-socketio backend
"""

import secrets
from contextlib import asynccontextmanager
from pathlib import Path

import socketio
import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from backend.src import __version__, __codename__
from backend.src.config import Config
from backend.src.log_levels import apply_log_levels
from backend.src.emby_client import EmbyClient
from backend.src.party_manager import PartyManager
from backend.src.hls_token_manager import HLSTokenManager
from backend.src.stream_builder import StreamBuilder
from backend.src.avatar_store import AvatarStore
from backend.src.admin_session_store import AdminSessionStore
from backend.src.rate_limit import RateLimitMiddleware, SlidingWindowRateLimiter
from backend.src.update_checker import check_for_updates
from backend.src.routers import auth, library, media, hls, party, admin, avatar, health, quality
from backend.src.socket_handlers import register_all as register_socket_handlers

# Load .env BEFORE any module-level os.getenv() runs. Several settings
# below (SESSION_SECRET, SESSION_COOKIE_SECURE, CORS_ALLOWED_ORIGINS) are
# read at import time via raw os.getenv(), which executes before the
# first Config.from_env() call further down. Without this eager load,
# those three would always fall back to their defaults (ephemeral session
# key, insecure cookie, CORS '*') no matter what the .env file said --
# while the values that flow through Config appeared to work, producing
# the confusing "some .env keys apply, some don't" symptom. load_dotenv
# is idempotent, so the later Config.from_env() re-read is harmless.
from dotenv import load_dotenv as _load_dotenv
_load_dotenv(Path(__file__).parent.parent / '.env')


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
    config.validate_for_startup()
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
    admin_session_store = AdminSessionStore(ttl_seconds=config.SESSION_EXPIRY)
    rate_limiter = SlidingWindowRateLimiter()
    http_client = httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=5.0, pool=5.0),
        follow_redirects=False,
    )

    logger.info(f"Emby Server: {config.EMBY_SERVER_URL}")
    if config.APP_PREFIX:
        logger.info(f"App Prefix: {config.APP_PREFIX}")
    # Loud warning for the ephemeral-session-secret case. See app.py:151
    # for the SESSION_SECRET load logic. When this path fires, every
    # restart invalidates all cookies (fine for dev, not for prod), and
    # under gunicorn/uvicorn --workers >1 each worker signs with its
    # own key so session state becomes non-deterministic per request.
    if _session_ephemeral:
        logger.warning(
            "SESSION_SECRET env var is empty; using an ephemeral random "
            "key. All party cookies invalidate on next restart, and "
            "multi-worker deployments will exhibit non-deterministic "
            "session state. Generate a stable key with "
            "`openssl rand -hex 32` and set SESSION_SECRET in .env."
        )
    if not _session_cookie_secure:
        logger.info(
            "SESSION_COOKIE_SECURE=false: session cookie will ride "
            "plain HTTP. Set SESSION_COOKIE_SECURE=true in production."
        )
    # Loud startup banner for the hidden dev-host gate. Two env vars
    # gate this jointly so a stray .env carried in from elsewhere
    # can't accidentally arm "anyone becomes host" mode: setting
    # EMBY_WATCHPARTY_X_DEV_HOST alone is intentionally a no-op until
    # the operator also sets EMBY_WATCHPARTY_X_DEV_HOST_ACCEPT_RISK=true
    # as an explicit acknowledgement. See backend/src/routers/auth.py
    # for the gate; the var names are intentionally kept off /admin
    # and out of .env.example.
    import os as _os
    _dev_host_set = bool(_os.getenv("EMBY_WATCHPARTY_X_DEV_HOST", "").strip())
    _dev_host_ack = _os.getenv("EMBY_WATCHPARTY_X_DEV_HOST_ACCEPT_RISK", "").strip().lower() == "true"
    if _dev_host_set and _dev_host_ack:
        logger.warning(
            "DEV GATE ACTIVE: EMBY_WATCHPARTY_X_DEV_HOST is set and the "
            "risk is acknowledged. Any /api/auth/login call OR new party "
            "join will auto-promote the caller using the stored "
            "credentials. Do NOT leave this set in production deployments."
        )
    elif _dev_host_set and not _dev_host_ack:
        logger.error(
            "DEV GATE MISCONFIGURED: EMBY_WATCHPARTY_X_DEV_HOST is set "
            "but EMBY_WATCHPARTY_X_DEV_HOST_ACCEPT_RISK is not 'true'. "
            "The gate is DISABLED. Set the second var to 'true' to arm it, "
            "or remove DEV_HOST entirely if you didn't mean to set either."
        )
    logger.info("Components initialized successfully")

    # Store on app.state for dependency injection
    app.state.config = config
    app.state.logger = logger
    app.state.emby_client = emby_client
    app.state.party_manager = party_manager
    app.state.token_manager = token_manager
    app.state.stream_builder = stream_builder
    app.state.avatar_store = avatar_store
    app.state.admin_session_store = admin_session_store
    app.state.rate_limiter = rate_limiter
    app.state.http_client = http_client
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
    await http_client.aclose()


# Create SocketIO server.
#
# max_http_buffer_size: 128 KiB. Default is 1 MB; nothing legitimate on
# our wire needs more (chat messages, small JSON events). Shrinking the
# ceiling defangs the socketio DoS vector we just patched around
# (CVE-2026-48804) and caps any future single-packet amplification
# attempt at the transport layer.
#
# ping_timeout / ping_interval: default socket.io values (60s / 25s)
# leave a dead client eating a slot for a full minute. Halving both
# means a client-crash / zombie-tab reconnect storm reclaims resources
# ~2x faster.
#
# cors_allowed_origins: read from env. Comma-separated list; the
# historical default '*' means "any origin can XHR-poll the server",
# which combined with the missing per-IP throttle amplifies cross-
# origin DoS. Production deploys should pin to their actual origin(s).
import os as _os_sio
_allowed_origins_raw = _os_sio.getenv("CORS_ALLOWED_ORIGINS", "*").strip()
if _allowed_origins_raw == "*":
    _cors_origins = "*"
else:
    _cors_origins = [o.strip() for o in _allowed_origins_raw.split(",") if o.strip()]
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins=_cors_origins,
    max_http_buffer_size=128 * 1024,
    ping_timeout=30,
    ping_interval=12,
)

# Create FastAPI app
app = FastAPI(
    title="Emby Watch Party",
    version=__version__,
    description="Synchronized video watching for Emby media servers",
    lifespan=lifespan,
)
app.add_middleware(RateLimitMiddleware)

# Session middleware. Secret is loaded from the SESSION_SECRET env var
# and MUST persist across process restarts and across every uvicorn
# worker so signed cookies remain verifiable. Previously this was
# `secrets.token_hex(32)` at module load, which meant every restart
# ejected every user from their party (401 on the next request), and
# with --workers >1 each worker signed with a different key so session
# state became non-deterministic per request. When the env var is
# absent, we generate an ephemeral key AND log a loud warning -- fine
# for local dev, catastrophic in production. Ops docs point at
# `openssl rand -hex 32` as the recipe.
#
# Cookie hardening:
# - same_site='lax'  keeps top-level GET navigations working (needed
#                    for share links landing on /party/<code>) while
#                    blocking cross-site POST CSRF against /api/party/*.
# - https_only        read from SESSION_COOKIE_SECURE env var. True in
#                    production, False in local dev (default). When True
#                    the cookie only rides HTTPS requests, closing the
#                    plaintext-leak vector on the party-bound session.
# - max_age          14 days matches the Starlette default explicitly.
import os as _os_session
SESSION_SECRET = _os_session.getenv("SESSION_SECRET", "").strip()
_session_ephemeral = False
if not SESSION_SECRET:
    SESSION_SECRET = secrets.token_hex(32)
    _session_ephemeral = True
_session_cookie_secure = _os_session.getenv(
    "SESSION_COOKIE_SECURE", "false"
).strip().lower() == "true"
app.add_middleware(
    SessionMiddleware,
    secret_key=SESSION_SECRET,
    session_cookie="ewp_session",
    max_age=14 * 24 * 60 * 60,
    same_site="lax",
    https_only=_session_cookie_secure,
)

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
