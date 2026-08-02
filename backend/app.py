"""Emby Watch Party ASGI application and application factory."""

from __future__ import annotations

import json
import secrets
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

import httpx
import socketio
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from backend.src import __codename__, __version__
from backend.src.admin_session_store import AdminSessionStore
from backend.src.avatar_store import AvatarStore
from backend.src.config import Config
from backend.src.emby_client import EmbyClient
from backend.src.emby_gateway import EmbyGateway
from backend.src.hls_token_manager import HLSTokenManager
from backend.src.log_levels import apply_log_levels
from backend.src.observability import RequestLogMiddleware
from backend.src.party_manager import PartyManager
from backend.src.rate_limit import RateLimitMiddleware, SlidingWindowRateLimiter
from backend.src.routers import admin, auth, avatar, health, hls, library, media, party, quality
from backend.src.socket_handlers import register_all as register_socket_handlers
from backend.src.stream_builder import StreamBuilder
from backend.src.update_checker import check_for_updates

PROJECT_ROOT = Path(__file__).parent.parent
STATIC_ROOT = Path(__file__).parent / "static"


async def _shutdown_runtime(
    application: FastAPI,
    socket_context: dict,
    admin_sessions: AdminSessionStore,
    tokens: HLSTokenManager,
    limiter: SlidingWindowRateLimiter,
    logger,
) -> None:
    """Release runtime-owned resources, including partial startup state."""
    logger.info("Shutting down")
    await socket_context["party_lifecycle"].dissolve_all(reason="shutdown")
    await application.state.sio.shutdown()
    logger.info(
        "cleanup operation=shutdown outcome=ok session_cleanup=%s "
        "token_cleanup=%s limiter_cleanup=%s",
        admin_sessions.clear(),
        tokens.revoke_all(),
        limiter.clear_all(),
    )


def _setup_logging(config: Config):
    from rsyslog_logger import setup_logger

    logger = setup_logger(
        name="emby-watchparty",
        log_file=config.LOG_FILE if config.LOG_TO_FILE else None,
        log_level=config.LOG_LEVEL,
        log_format=config.LOG_FORMAT,
        console_log_level=config.CONSOLE_LOG_LEVEL,
        max_size=config.LOG_MAX_SIZE,
        backup_count=5,
    )
    apply_log_levels(config)
    return logger


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Own every process-scoped resource used by this application instance."""
    config: Config = application.state.bootstrap_config
    config.validate_for_startup()
    logger = _setup_logging(config)
    root: Path = application.state.project_root

    async with AsyncExitStack() as resources:
        # Acquire the process-wide HTTP client first so every later startup
        # failure still closes its transport through the exit stack.
        http_client = await resources.enter_async_context(
            httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=5.0, pool=5.0),
                follow_redirects=False,
                transport=application.state.http_transport,
            )
        )
        party_manager = PartyManager(config, logger)
        token_manager = HLSTokenManager(config, logger)
        avatar_store = AvatarStore(
            db_path=root / "data" / "avatars.db",
            avatars_dir=root / "images" / "avatars",
            logger=logger,
        )
        admin_session_store = AdminSessionStore(ttl_seconds=config.SESSION_EXPIRY)
        rate_limiter = SlidingWindowRateLimiter()
        emby_gateway = EmbyGateway(http_client, config.EMBY_SERVER_URL, logger)
        emby_client = EmbyClient(config.EMBY_SERVER_URL, config.EMBY_API_KEY, logger, emby_gateway)
        stream_builder = StreamBuilder(emby_client, logger, config)

        application.state.config = config
        application.state.logger = logger
        application.state.emby_client = emby_client
        application.state.party_manager = party_manager
        application.state.token_manager = token_manager
        application.state.stream_builder = stream_builder
        application.state.avatar_store = avatar_store
        application.state.admin_session_store = admin_session_store
        application.state.rate_limiter = rate_limiter
        application.state.http_client = http_client
        application.state.emby_gateway = emby_gateway

        socket_context = register_socket_handlers(
            application.state.sio,
            emby_client,
            party_manager,
            token_manager,
            stream_builder,
            config,
            logger,
            session_secret=application.state.session_secret,
            rate_limiter=rate_limiter,
        )
        application.state.socket_context = socket_context
        resources.push_async_callback(
            _shutdown_runtime,
            application,
            socket_context,
            admin_session_store,
            token_manager,
            rate_limiter,
            logger,
        )

        logger.info('Emby Watch Party v%s - "%s"', __version__, __codename__)
        logger.info("Emby Server: %s", config.EMBY_SERVER_URL)
        if application.state.session_ephemeral:
            logger.warning(
                "SESSION_SECRET is empty; using an ephemeral key. Sessions expire on restart."
            )
        if application.state.enable_update_check:
            await check_for_updates(http_client, logger)

        yield


def _install_api_and_socket_routes(application: FastAPI, prefix: str) -> None:
    for api_router in (
        auth.router,
        library.router,
        media.router,
        hls.router,
        party.router,
        admin.router,
        avatar.router,
        health.router,
        quality.router,
    ):
        application.include_router(api_router, prefix=prefix)

    socket_path = f"{prefix}/socket.io"
    application.mount(
        socket_path,
        socketio.ASGIApp(application.state.sio, socketio_path=socket_path),
    )


def _install_static_routes(application: FastAPI, prefix: str, static_root: Path) -> None:
    index_path = static_root / "index.html"
    assets_path = static_root / "assets"
    if not index_path.exists() or not assets_path.exists():
        return

    application.mount(
        f"{prefix}/assets",
        StaticFiles(directory=str(assets_path)),
        name="assets",
    )

    def rendered_index() -> str:
        html = index_path.read_text(encoding="utf-8")
        base_href = f"{prefix}/" if prefix else "/"
        injection = (
            f'<base href="{base_href}"><script>window.APP_PREFIX = {json.dumps(prefix)};</script>'
        )
        return html.replace("<head>", "<head>" + injection, 1)

    @application.get(prefix or "/", include_in_schema=False)
    async def serve_spa_root():
        return HTMLResponse(rendered_index())

    if prefix:

        @application.get("/", include_in_schema=False)
        async def redirect_root_to_prefix():
            return RedirectResponse(url=f"{prefix}/")

    @application.get(f"{prefix}/{{full_path:path}}", include_in_schema=False)
    async def serve_spa(full_path: str):
        del full_path
        return HTMLResponse(rendered_index())


def create_app(
    *,
    config: Config | None = None,
    project_root: Path | None = None,
    static_root: Path | None = None,
    enable_update_check: bool = True,
    http_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Build an isolated app instance suitable for production or public tests."""
    resolved_config = config or Config.from_env()
    prefix = resolved_config.APP_PREFIX
    session_secret = resolved_config.SESSION_SECRET or secrets.token_hex(32)
    origins: str | list[str]
    if resolved_config.CORS_ALLOWED_ORIGINS == ("*",):
        origins = "*"
    else:
        origins = list(resolved_config.CORS_ALLOWED_ORIGINS)

    sio = socketio.AsyncServer(
        async_mode="asgi",
        cors_allowed_origins=origins,
        max_http_buffer_size=128 * 1024,
        ping_timeout=30,
        ping_interval=12,
    )
    application = FastAPI(
        title="Emby Watch Party",
        version=__version__,
        description="Synchronized video watching for Emby media servers",
        lifespan=lifespan,
    )
    application.state.bootstrap_config = resolved_config
    application.state.project_root = Path(project_root or PROJECT_ROOT)
    application.state.http_transport = http_transport
    application.state.enable_update_check = enable_update_check
    application.state.session_secret = session_secret
    application.state.session_ephemeral = not bool(resolved_config.SESSION_SECRET)
    application.state.sio = sio

    application.add_middleware(RateLimitMiddleware)
    application.add_middleware(RequestLogMiddleware)
    application.add_middleware(
        SessionMiddleware,
        secret_key=session_secret,
        session_cookie="ewp_session",
        max_age=14 * 24 * 60 * 60,
        same_site="lax",
        https_only=resolved_config.SESSION_COOKIE_SECURE,
    )
    _install_api_and_socket_routes(application, prefix)
    _install_static_routes(application, prefix, Path(static_root or STATIC_ROOT))
    return application


app = create_app()
sio = app.state.sio


if __name__ == "__main__":
    import uvicorn

    cfg = app.state.bootstrap_config
    uvicorn.run(
        app,
        host=cfg.WATCH_PARTY_BIND,
        port=cfg.WATCH_PARTY_PORT,
        proxy_headers=False,
    )
