"""
Flask Routes Package
Split into modules for maintainability. Each module registers its routes on the shared blueprint.
"""

from flask import Blueprint, session, redirect
from functools import wraps

from src.routes.pages import register as register_pages
from src.routes.auth import register as register_auth
from src.routes.library import register as register_library
from src.routes.media import register as register_media
from src.routes.hls import register as register_hls
from src.routes.party_api import register as register_party_api
from src.routes.admin import register as register_admin


def init_routes(app, emby_client, party_manager, config, logger, limiter=None,
                token_manager=None, stream_builder=None):
    """
    Initialize all Flask routes with dependency injection.

    During the 2.0 transition, route modules still use the deps dict pattern.
    The new services are bridged through compatibility shims in deps.
    """
    from src.utils import generate_random_username, generate_party_code

    app_prefix = config.APP_PREFIX if hasattr(config, 'APP_PREFIX') else getattr(config, 'APP_PREFIX', '')

    bp = Blueprint(
        'main',
        __name__,
        url_prefix=app_prefix if app_prefix else None,
        static_folder='../../static',
        static_url_path='/static',
    )

    def prefixed_url(path):
        if app_prefix:
            return f"{app_prefix}{path}"
        return path

    def login_required(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            logger.debug(f"[AUTH CHECK] REQUIRE_LOGIN={config.REQUIRE_LOGIN}, authenticated={'authenticated' in session}")
            if config.REQUIRE_LOGIN and 'authenticated' not in session:
                logger.debug("[AUTH CHECK] Redirecting to login page")
                return redirect(prefixed_url('/login'))
            logger.debug("[AUTH CHECK] Access granted")
            return f(*args, **kwargs)
        return decorated_function

    deps = {
        'bp': bp,
        'emby_client': emby_client,
        'party_manager': party_manager,
        'config': config,
        'logger': logger,
        'limiter': limiter,
        'watch_parties': party_manager.get_all(),
        'app_prefix': app_prefix,
        'prefixed_url': prefixed_url,
        'login_required': login_required,
        # New services
        'token_manager': token_manager,
        'stream_builder': stream_builder,
        # Utils
        'generate_random_username': generate_random_username,
        'generate_party_code': generate_party_code,
    }

    # Legacy shims for validate_hls_token / get_user_token
    if token_manager:
        deps['hls_tokens'] = token_manager._tokens
        deps['validate_hls_token'] = lambda token, ht, wp, cfg, lg, item_id=None: (
            token_manager.validate(
                token,
                party_exists_fn=party_manager.exists,
                user_in_party_fn=lambda pid, sid: party_manager.get(pid) is not None and sid in party_manager.get(pid)["users"],
            )
        )
        deps['get_user_token'] = lambda pid, sid, ht, cfg, lg: token_manager.get_or_create(pid, sid)
        deps['generate_hls_token'] = lambda pid, sid, ht, cfg, lg: token_manager.generate(pid, sid)
    else:
        deps['hls_tokens'] = {}
        deps['validate_hls_token'] = lambda token, ht, wp, cfg, lg, item_id=None: True
        deps['get_user_token'] = lambda pid, sid, ht, cfg, lg: None
        deps['generate_hls_token'] = lambda pid, sid, ht, cfg, lg: None

    register_pages(deps)
    register_auth(deps)
    register_library(deps)
    register_media(deps)
    register_hls(deps)
    register_party_api(deps)
    register_admin(deps)

    app.register_blueprint(bp)
