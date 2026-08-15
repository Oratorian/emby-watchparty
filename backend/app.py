"""Emby Watch Party ASGI application and application factory."""

from __future__ import annotations

import json
import logging
import secrets
import sys
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

import httpx
import socketio
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from backend.src import __codename__, __version__
from backend.src.admin_session_store import AdminSessionStore
from backend.src.avatar_store import AvatarStore
from backend.src.config import Config
from backend.src.emby_gateway import MediaServerGateway
from backend.src.hls_token_manager import HLSTokenManager
from backend.src.log_levels import apply_log_levels
from backend.src.observability import RequestLogMiddleware
from backend.src.party_manager import PartyManager
from backend.src.providers import create_provider
from backend.src.rate_limit import RateLimitMiddleware, SlidingWindowRateLimiter
from backend.src.routers import admin, auth, avatar, health, hls, library, media, party, quality
from backend.src.socket_handlers import register_all as register_socket_handlers
from backend.src.stream_builder import StreamBuilder
from backend.src.update_checker import check_for_updates

PROJECT_ROOT = Path(__file__).parent.parent
STATIC_ROOT = Path(__file__).parent / "static"


def _json_for_html_script(value: str) -> str:
    return json.dumps(value).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


def _describe_boot_errors(config: Config) -> str:
    return "; ".join(
        f"{name}: {message}" for name, message in sorted(config.startup_errors().items())
    )


@asynccontextmanager
async def unconfigured_lifespan(application: FastAPI):
    """Unconfigured mode owns logging and nothing else."""
    config = application.state.bootstrap_config
    logger = _setup_logging(config)
    application.state.logger = logger
    logger.error(
        "Refusing to serve: invalid boot configuration. Fix these in the "
        "environment and restart -- %s",
        _describe_boot_errors(config),
    )
    yield


def _create_setup_app(config: Config, project_root: Path) -> FastAPI:
    """Serve a diagnosis, and nothing else, when boot config is invalid.

    Configuration is environment-only. There is deliberately no setup
    form and no bootstrap token here, because the interactive flow that
    used to live in this function could not work where the product is
    actually deployed.

    Every field arrives through the environment on Unraid, CasaOS,
    Portainer and TrueNAS, and `EnvConfig.from_env` resolves
    os.environ -> .env -> persisted -> defaults. So a submitted form was
    short-circuited back to the current value for every field an
    operator had set, which on those platforms is all of them: the page
    silently discarded edits and wrote the same broken value back. The
    token it was gated behind had to be recovered from container logs or
    a root-owned 0600 file, which is unreadable over the appdata share
    those platforms hand you.

    It bought no security either. Environment beats the persisted file,
    so an attacker who won the unconfigured-instance race is overridden
    by the variable you were always going to set, and anyone able to
    read the token from logs or the volume already has host access.

    What remains is the part that was worth keeping: name the invalid
    fields loudly, stay up so an orchestrator can diagnose rather than
    restart-loop, and refuse to serve anything else.
    """
    application = FastAPI(
        title="Emby Watch Party (unconfigured)",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=unconfigured_lifespan,
    )
    application.state.bootstrap_config = config
    application.state.project_root = project_root

    # Written straight to stderr, before any logging configuration, and
    # banner-framed on purpose. On appliance platforms this is read
    # through a web log viewer, where a single line among startup noise
    # is missed; this is the only diagnosis the operator now gets.
    detail = _describe_boot_errors(config)
    print(
        "",
        "=" * 72,
        "  Emby Watch Party cannot start: invalid boot configuration.",
        "",
        *(f"    {item}" for item in detail.split("; ")),
        "",
        "  Set these in the environment (container template, compose",
        "  environment:, or .env) and restart. Nothing else is served",
        "  until they are valid.",
        "=" * 72,
        "",
        sep="\n",
        file=sys.stderr,
        flush=True,
    )

    prefix = "" if "APP_PREFIX" in config.startup_errors() else config.APP_PREFIX
    application.add_middleware(RequestLogMiddleware)

    @application.get(f"{prefix}/api/health", include_in_schema=False)
    async def setup_health():
        return {"status": "setup_required", "version": __version__, "codename": __codename__}

    @application.get(f"{prefix}/api/ready", include_in_schema=False)
    async def setup_ready():
        return JSONResponse({"status": "setup_required"}, status_code=503)

    @application.api_route(
        "/{full_path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
        include_in_schema=False,
    )
    async def setup_unavailable(full_path: str):
        del full_path
        return JSONResponse({"status": "setup_required"}, status_code=503)

    return application


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


def _remove_stale_setup_artifacts(root: Path, logger) -> None:
    """Remove obsolete setup files only after runtime startup succeeds."""
    for name in ("bootstrap.json", "setup-token"):
        path = root / "data" / name
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("Could not remove obsolete setup artifact %s: %s", name, exc)


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

    # uvicorn runs a second access logger, independent of ours, and it
    # writes the full request line at INFO with the query string
    # included. Every HLS URL carries ?token=<hls token>, so leaving it
    # enabled publishes a working stream credential on every playlist
    # and segment request, into anything that ships logs onward.
    #
    # Suppressed here rather than through uvicorn.run(access_log=False)
    # because that only covers `python -m backend.app`. Starting via the
    # ASGI target instead, `uvicorn backend.app:app --reload`, bypasses
    # main() completely and kept leaking.
    #
    # Disabled rather than filtered, deliberately. A filter would have to
    # rewrite uvicorn's internal record.args, and if that shape changed
    # on an upgrade the failure mode would be a silent re-leak. Nothing
    # observable is lost: RequestLogMiddleware already emits a structured
    # line per request built from request.url.path, which carries no
    # query string.
    logging.getLogger("uvicorn.access").disabled = True

    return logger


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Own every process-scoped resource used by this application instance."""
    config: Config = application.state.bootstrap_config
    config.validate_for_startup()
    logger = _setup_logging(config)
    for warning in config.boot_warnings():
        logger.warning(warning)
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
        media_server_gateway = MediaServerGateway(http_client, config.MEDIA_SERVER_URL, logger)
        media_server = create_provider(config, logger, media_server_gateway)
        stream_builder = StreamBuilder(media_server.client, logger, config)

        application.state.config = config
        application.state.logger = logger
        application.state.media_server = media_server
        # Compatibility aliases while v1 routes retain historical dependency names.
        application.state.emby_client = media_server
        application.state.party_manager = party_manager
        application.state.token_manager = token_manager
        application.state.stream_builder = stream_builder
        application.state.avatar_store = avatar_store
        application.state.admin_session_store = admin_session_store
        application.state.rate_limiter = rate_limiter
        application.state.http_client = http_client
        application.state.media_server_gateway = media_server_gateway
        application.state.emby_gateway = media_server_gateway

        socket_context = register_socket_handlers(
            application.state.sio,
            media_server,
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
        logger.info("%s Server: %s", media_server.identity.display_name, config.MEDIA_SERVER_URL)
        if application.state.session_ephemeral:
            logger.warning(
                "SESSION_SECRET is empty; using an ephemeral key. Sessions expire on restart."
            )
        if application.state.enable_update_check:
            await check_for_updates(http_client, logger)

        _remove_stale_setup_artifacts(root, logger)

        yield


async def _upstream_unavailable(_request, exc: httpx.HTTPError) -> JSONResponse:
    """Any Emby transport failure that reaches here is a bad gateway, not a bug.

    Registered once rather than per route. Thirteen of the eighteen library
    routes had no such mapping, so a timeout or refused connection surfaced as
    a bare 500: indistinguishable from an application fault, and it told the
    operator to look in the wrong place. Routes that map it themselves are
    unaffected, since their own handler runs first.
    """
    logging.getLogger("watchparty.upstream").warning(
        "Emby upstream unavailable: %s", type(exc).__name__
    )
    return JSONResponse(status_code=502, content={"detail": "Emby upstream unavailable"})


def _install_api_and_socket_routes(application: FastAPI, prefix: str) -> None:
    application.add_exception_handler(httpx.HTTPError, _upstream_unavailable)  # type: ignore[arg-type]
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
        serialized_prefix = _json_for_html_script(prefix)
        injection = (
            f'<base href="{base_href}"><script>window.APP_PREFIX = {serialized_prefix};</script>'
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
    resolved_root = Path(project_root or PROJECT_ROOT)
    resolved_config = config or Config.from_env(resolved_root)
    try:
        resolved_config.validate_for_startup()
    except ValueError:
        return _create_setup_app(resolved_config, resolved_root)
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
    application.state.project_root = resolved_root
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
        # `.env.example` calls SESSION_EXPIRY "Session cookie lifetime in
        # seconds", and this was a hardcoded 14 days, so the setting did not
        # do the one thing it documented. It governed only the admin session
        # store's TTL, which meant the cookie outlived the admin session by
        # thirteen days at the shipped defaults.
        max_age=resolved_config.SESSION_EXPIRY,
        same_site="lax",
        https_only=resolved_config.SESSION_COOKIE_SECURE,
    )
    _install_api_and_socket_routes(application, prefix)
    _install_static_routes(application, prefix, Path(static_root or STATIC_ROOT))
    return application


# Construction is deliberately NOT performed at module scope.
#
# `create_app()` reads the ambient environment and, when boot config does
# not validate, builds the setup app -- which mints a bootstrap token,
# prints it to stdout and writes data/setup-token. As a module-level
# statement that fired on *import*, so `import backend.app` (which
# tests/conftest.py and every test module do) minted and leaked a fresh
# admin credential each time, and rewrote the token file out from under
# a running instance. It only stayed out of CI logs because pytest
# captures stdout during collection, which is luck rather than a
# control: one `-s` and the token lands in a public Actions log.
#
# It also undid the point of the factory. The app is meant to be built
# by a call so tests get an isolated instance per case; a module-level
# singleton reintroduced exactly the import-time construction the
# factory exists to remove.
#
# `app` and `sio` remain reachable as module attributes via PEP 562, so
# an ASGI target like `uvicorn backend.app:app` still resolves for
# anyone running a custom unit file. The difference is that the work now
# happens on first *attribute access* rather than on import, and the
# instance is memoised so repeated access does not re-mint anything.
_lazy_app: FastAPI | None = None


def _module_app() -> FastAPI:
    global _lazy_app
    if _lazy_app is None:
        _lazy_app = create_app()
    return _lazy_app


def __getattr__(name: str) -> object:
    if name == "app":
        return _module_app()
    if name == "sio":
        return getattr(_module_app().state, "sio", None)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def main() -> None:
    """Entry point for `python -m backend.app`, the documented way to run."""
    import uvicorn

    application = create_app()
    cfg = application.state.bootstrap_config
    startup_errors = cfg.startup_errors()
    port = 5000 if "WATCH_PARTY_PORT" in startup_errors else cfg.WATCH_PARTY_PORT
    uvicorn.run(
        application,
        host=cfg.WATCH_PARTY_BIND,
        port=port,
        proxy_headers=False,
        # Belt to _setup_logging's braces. That disables the
        # `uvicorn.access` logger for every entrypoint; this states the
        # same intent natively for the one entrypoint that runs uvicorn
        # itself, so nobody reading main() has to know about the other.
        access_log=False,
    )


if __name__ == "__main__":
    main()
