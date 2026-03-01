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


def init_routes(app, emby_client, party_manager, config, logger, limiter=None):
    """
    Initialize all Flask routes with dependency injection

    Args:
        app: Flask application instance
        emby_client: EmbyClient instance
        party_manager: PartyManager instance
        config: Configuration module
        logger: Logger instance
        limiter: Optional Flask-Limiter instance
    """
    from src.utils import (
        generate_random_username,
        generate_party_code,
        generate_hls_token,
        validate_hls_token,
        get_user_token,
    )

    # Get APP_PREFIX for URL building
    app_prefix = getattr(config, 'APP_PREFIX', '')

    # Create a blueprint with the APP_PREFIX as url_prefix
    bp = Blueprint(
        'main',
        __name__,
        url_prefix=app_prefix if app_prefix else None,
        static_folder='../../static',
        static_url_path='/static'
    )

    # Helper function to build URLs with APP_PREFIX (for redirects)
    def prefixed_url(path):
        """Build URL with APP_PREFIX"""
        if app_prefix:
            return f"{app_prefix}{path}"
        return path

    # Authentication decorator
    def login_required(f):
        """Decorator to require login if REQUIRE_LOGIN is enabled"""
        @wraps(f)
        def decorated_function(*args, **kwargs):
            logger.debug(f"[AUTH CHECK] REQUIRE_LOGIN={config.REQUIRE_LOGIN}, authenticated={'authenticated' in session}")
            if config.REQUIRE_LOGIN == 'true' and 'authenticated' not in session:
                logger.debug(f"[AUTH CHECK] Redirecting to login page")
                return redirect(prefixed_url('/login'))
            logger.debug(f"[AUTH CHECK] Access granted")
            return f(*args, **kwargs)
        return decorated_function

    # Shared dependencies passed to each route module
    deps = {
        'bp': bp,
        'emby_client': emby_client,
        'party_manager': party_manager,
        'config': config,
        'logger': logger,
        'limiter': limiter,
        'watch_parties': party_manager.watch_parties,
        'hls_tokens': party_manager.hls_tokens,
        'app_prefix': app_prefix,
        'prefixed_url': prefixed_url,
        'login_required': login_required,
        # Utils
        'generate_random_username': generate_random_username,
        'generate_party_code': generate_party_code,
        'generate_hls_token': generate_hls_token,
        'validate_hls_token': validate_hls_token,
        'get_user_token': get_user_token,
    }

    # Register all route modules
    register_pages(deps)
    register_auth(deps)
    register_library(deps)
    register_media(deps)
    register_hls(deps)
    register_party_api(deps)

    # Register the blueprint with the app
    app.register_blueprint(bp)
