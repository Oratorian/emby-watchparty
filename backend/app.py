"""Emby Watch Party ASGI application and application factory."""

from __future__ import annotations

import html
import json
import logging
import secrets
import sys
import threading
from contextlib import AsyncExitStack, asynccontextmanager, suppress
from pathlib import Path

import httpx
import socketio
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from backend.src import __codename__, __version__
from backend.src.admin_session_store import AdminSessionStore
from backend.src.avatar_store import AvatarStore
from backend.src.bootstrap import (
    SetupAttemptLimiter,
    save_bootstrap_config,
    save_setup_token,
    validate_bootstrap_submission,
)
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
SETUP_BODY_LIMIT = 32 * 1024


def _json_for_html_script(value: str) -> str:
    return json.dumps(value).replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")


async def _read_setup_body(request: Request) -> bytes | None:
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > SETUP_BODY_LIMIT:
            return None
        body.extend(chunk)
    return bytes(body)


def _setup_html(config: Config, prefix: str, *, saved: bool) -> str:
    if saved:
        return """<!doctype html><html><head><meta charset="utf-8"><title>Setup saved</title>
<style>body{font:16px system-ui;background:#0b1220;color:#e5edf8;max-width:48rem;margin:5rem auto;padding:2rem}main{background:#142033;padding:2rem;border-radius:16px}h1{color:#60d5ff}</style>
</head><body><main><h1>Configuration saved; restart required.</h1><p>Restart Emby Watch Party to load boot settings. This process will not restart itself.</p></main></body></html>"""

    esc = html.escape
    mode = config.APP_ENV if config.APP_ENV in {"development", "production"} else "production"
    cors = ", ".join(config.CORS_ALLOWED_ORIGINS)
    proxies = ", ".join(config.TRUSTED_PROXY_CIDRS)
    endpoint = _json_for_html_script(f"{prefix}/api/setup")
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Emby Watch Party setup</title><style>
:root{{color-scheme:dark;font:16px system-ui}}body{{margin:0;background:#08111f;color:#e8f1fb}}main{{max-width:52rem;margin:2rem auto;padding:2rem;background:#111f33;border-radius:18px}}h1{{color:#66d9ff}}label{{display:block;font-weight:650;margin-top:1rem}}input,select{{box-sizing:border-box;width:100%;padding:.7rem;margin-top:.35rem;border:1px solid #52657d;border-radius:7px;background:#091524;color:#fff}}input[type=checkbox]{{width:auto;margin-right:.5rem}}small{{display:block;color:#b5c4d7;margin-top:.3rem}}button{{margin-top:1rem;padding:.75rem 1rem;border:0;border-radius:7px;background:#16a7d4;color:#041019;font-weight:700;cursor:pointer}}button.secondary{{background:#33465f;color:#fff}}#errors{{color:#ff9b9b;white-space:pre-wrap}}.notice{{padding:1rem;background:#20334d;border-left:4px solid #66d9ff}}</style></head>
<body><main><h1>First-run configuration</h1>
<p class="notice">Boot-setting changes require restart. Token shown in server console is required to save. Never share it or place it in a URL.</p>
<p>Local plain HTTP uses development mode and a non-secure cookie. Reverse-proxied HTTPS uses production mode, a secure cookie, and explicit public origin.</p>
<form id="setup-form" autocomplete="off">
<label>Deployment mode<select name="APP_ENV"><option value="development"{" selected" if mode == "development" else ""}>Local development</option><option value="production"{" selected" if mode == "production" else ""}>Production HTTPS</option></select></label>
<label>Emby server URL<input name="EMBY_SERVER_URL" type="url" value="{esc(config.EMBY_SERVER_URL, quote=True)}" required><small>HTTP(S) URL reachable by server.</small></label>
<label>Emby API key<input name="EMBY_API_KEY" type="password" value="" autocomplete="new-password"><small>Leave blank only to retain an already configured key.</small></label>
<label>Session secret<input name="SESSION_SECRET" type="password" value="" minlength="32" autocomplete="new-password"></label>
<button type="button" class="secondary" id="generate-secret">Generate secure secret</button>
<label><input name="SESSION_COOKIE_SECURE" type="checkbox"{" checked" if config.SESSION_COOKIE_SECURE else ""}>Secure session cookie</label>
<label>Allowed CORS origins<input name="CORS_ALLOWED_ORIGINS" value="{esc(cors, quote=True)}"><small>Comma-separated public origins; wildcard forbidden in production.</small></label>
<label><input name="BEHIND_PROXY" type="checkbox"{" checked" if config.BEHIND_PROXY else ""}>Behind a reverse proxy<small>Tick if nginx, Caddy, Traefik or similar terminates client connections. Rate limiting keys on the connecting address, so if this is ticked the trusted CIDRs below are required, otherwise every viewer shares one bucket.</small></label>
<label>Trusted proxy CIDRs<input name="TRUSTED_PROXY_CIDRS" value="{esc(proxies, quote=True)}" placeholder="172.16.0.0/12"><small>Networks your proxies connect from. Required when the box above is ticked; leave empty when exposed directly.</small></label>
<label>Application prefix (optional)<input name="APP_PREFIX" value="{esc(config.APP_PREFIX, quote=True)}" placeholder="/watchparty"></label>
<label><input name="ENABLE_HLS_TOKEN_VALIDATION" type="checkbox"{" checked" if config.ENABLE_HLS_TOKEN_VALIDATION else ""}>Enable HLS token validation (required in production)</label>
<label>Bootstrap token<input name="BOOTSTRAP_TOKEN" type="password" value="" autocomplete="off" required><small>Copy from server console. Token is sent only in request header.</small></label>
<div id="errors" role="alert"></div><button type="submit">Validate and save</button></form>
<script>
const form=document.getElementById('setup-form');const errors=document.getElementById('errors');
document.getElementById('generate-secret').addEventListener('click',()=>{{const bytes=new Uint8Array(32);crypto.getRandomValues(bytes);form.elements.SESSION_SECRET.value=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');}});
form.addEventListener('submit',async(event)=>{{event.preventDefault();errors.textContent='';const token=form.elements.BOOTSTRAP_TOKEN.value;
const payload={{APP_ENV:form.elements.APP_ENV.value,EMBY_SERVER_URL:form.elements.EMBY_SERVER_URL.value,EMBY_API_KEY:form.elements.EMBY_API_KEY.value,SESSION_SECRET:form.elements.SESSION_SECRET.value,SESSION_COOKIE_SECURE:form.elements.SESSION_COOKIE_SECURE.checked,CORS_ALLOWED_ORIGINS:form.elements.CORS_ALLOWED_ORIGINS.value,TRUSTED_PROXY_CIDRS:form.elements.TRUSTED_PROXY_CIDRS.value,BEHIND_PROXY:form.elements.BEHIND_PROXY.checked,APP_PREFIX:form.elements.APP_PREFIX.value,ENABLE_HLS_TOKEN_VALIDATION:form.elements.ENABLE_HLS_TOKEN_VALIDATION.checked}};
try{{const response=await fetch({endpoint},{{method:'POST',headers:{{'Content-Type':'application/json','X-Emby-Watchparty-Setup-Token':token}},body:JSON.stringify(payload)}});const result=await response.json();
if(response.ok){{form.elements.EMBY_API_KEY.value='';form.elements.SESSION_SECRET.value='';form.elements.BOOTSTRAP_TOKEN.value='';document.body.innerHTML='<main><h1>Configuration saved; restart required.</h1><p>Restart server to enter normal mode.</p></main>';return;}}
errors.textContent=result.errors?Object.entries(result.errors).map(([field,message])=>field+': '+message).join('\n'):(result.detail||'Save failed');}}catch(_error){{errors.textContent='Save failed. Check server and try again.';}}}});
</script></main></body></html>"""


@asynccontextmanager
async def setup_lifespan(application: FastAPI):
    """Setup mode owns only logging and bootstrap recovery state."""
    config = application.state.bootstrap_config
    logger = _setup_logging(config)
    application.state.logger = logger
    logger.warning(
        "Setup required; invalid boot fields=%s token_file=%s",
        ",".join(sorted(config.startup_errors())),
        application.state.setup_token_path,
    )
    yield


def _create_setup_app(config: Config, project_root: Path) -> FastAPI:
    application = FastAPI(
        title="Emby Watch Party Setup",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=setup_lifespan,
    )
    application.state.bootstrap_config = config
    application.state.project_root = project_root
    bootstrap_token = secrets.token_urlsafe(32)
    setup_state: dict[str, object] = {"token": bootstrap_token, "saved": False}
    setup_lock = threading.Lock()
    setup_attempts = SetupAttemptLimiter()
    print(f"Emby Watch Party setup required. Bootstrap token: {bootstrap_token}", flush=True)
    token_path = save_setup_token(project_root, bootstrap_token)
    application.state.setup_token_path = token_path
    stderr_logger = logging.getLogger(f"emby-watchparty.setup.{id(application)}")
    stderr_logger.setLevel(logging.WARNING)
    stderr_logger.propagate = False
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    stderr_logger.addHandler(handler)
    try:
        stderr_logger.warning(
            "Setup required; invalid boot fields=%s; recovery token file=%s",
            ",".join(sorted(config.startup_errors())),
            token_path,
        )
    finally:
        stderr_logger.removeHandler(handler)
        handler.close()
    prefix = "" if "APP_PREFIX" in config.startup_errors() else config.APP_PREFIX
    application.add_middleware(RequestLogMiddleware)

    @application.get(f"{prefix}/setup", include_in_schema=False)
    async def setup_page():
        return HTMLResponse(
            _setup_html(config, prefix, saved=bool(setup_state["saved"])),
            headers={
                "Cache-Control": "no-store",
                "Content-Security-Policy": (
                    "default-src 'none'; style-src 'unsafe-inline'; "
                    "script-src 'unsafe-inline'; connect-src 'self'; "
                    "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
                ),
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @application.get(prefix or "/", include_in_schema=False)
    async def setup_root():
        return RedirectResponse(url=f"{prefix}/setup")

    if prefix:

        @application.get("/", include_in_schema=False)
        async def unprefixed_setup_root():
            return RedirectResponse(url=f"{prefix}/setup")

    @application.get(f"{prefix}/api/health", include_in_schema=False)
    async def setup_health():
        return {"status": "setup_required", "version": __version__, "codename": __codename__}

    @application.get(f"{prefix}/api/ready", include_in_schema=False)
    async def setup_ready():
        return JSONResponse({"status": "setup_required"}, status_code=503)

    @application.post(f"{prefix}/api/setup", include_in_schema=False)
    async def save_setup(request: Request):
        if setup_state["saved"]:
            return JSONResponse(
                {"status": "saved", "restart_required": True},
                status_code=409,
            )
        supplied = request.headers.get("X-Emby-Watchparty-Setup-Token", "")
        expected = str(setup_state["token"] or "disabled")
        token_matches = len(supplied) <= 1024 and secrets.compare_digest(supplied, expected)
        if not token_matches:
            peer = request.client.host if request.client else "unknown"
            decision = setup_attempts.record_failure(peer)
            request.app.state.logger.warning(
                "Failed bootstrap token attempt peer=%s limited=%s",
                peer,
                not decision.allowed,
            )
            if not decision.allowed:
                return JSONResponse(
                    {"detail": "Too many failed bootstrap token attempts"},
                    status_code=429,
                    headers={"Retry-After": str(decision.retry_after)},
                )
            return JSONResponse({"detail": "Invalid bootstrap token"}, status_code=403)
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > SETUP_BODY_LIMIT:
            return JSONResponse({"detail": "Request body too large"}, status_code=413)
        body = await _read_setup_body(request)
        if body is None:
            return JSONResponse({"detail": "Request body too large"}, status_code=413)
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JSONResponse(
                {"status": "invalid", "errors": {"FORM": "Invalid JSON request"}},
                status_code=400,
            )
        values, errors = validate_bootstrap_submission(config, payload)
        if errors:
            return JSONResponse(
                {"status": "invalid", "errors": errors},
                status_code=400,
            )
        with setup_lock:
            if setup_state["saved"]:
                return JSONResponse(
                    {"status": "saved", "restart_required": True},
                    status_code=409,
                )
            save_bootstrap_config(
                project_root,
                values,
                excluded_fields=config.explicit_env_fields,
            )
            setup_state["saved"] = True
            setup_state["token"] = None
            try:
                token_path.unlink()
            except OSError:
                request.app.state.logger.error(
                    "Failed to remove setup token recovery file path=%s",
                    token_path,
                )
        return {"status": "saved", "restart_required": True}

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
    bootstrap_path = resolved_root / "data" / "bootstrap.json"
    if config is None and not bootstrap_path.exists():
        save_bootstrap_config(resolved_root, {})
    with suppress(OSError):
        (resolved_root / "data" / "setup-token").unlink()
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
        max_age=14 * 24 * 60 * 60,
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
        # uvicorn's access logger writes the full request line, query
        # string included, at INFO. Every HLS URL carries ?token=<hls
        # token>, so leaving this on publishes a working stream
        # credential to the log on every playlist and segment request.
        # The redaction work only ever covered the `emby-watchparty`
        # logger, so this second logger in the same process quietly
        # undid it. RequestLogMiddleware already emits a structured line
        # per request built from request.url.path, which carries no
        # query string, so nothing observable is lost here.
        access_log=False,
    )


if __name__ == "__main__":
    main()
