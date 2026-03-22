"""
Update Checker
Checks GitHub for the latest release version
"""

import logging

import requests

from backend.src import __version__


def check_for_updates(logger: logging.Logger):
    """Check GitHub for latest release and log if update is available"""
    try:
        url = "https://api.github.com/repos/Oratorian/emby-watchparty/releases/latest"
        response = requests.get(url, timeout=5)

        if response.status_code == 200:
            data = response.json()
            latest = data.get("tag_name", "").lstrip("v")

            if latest and latest != __version__:
                logger.warning("=" * 60)
                logger.warning(f"UPDATE AVAILABLE: v{latest} (current: v{__version__})")
                logger.warning(
                    f"Download: {data.get('html_url', 'https://github.com/Oratorian/emby-watchparty/releases')}"
                )
                logger.warning("=" * 60)
            else:
                logger.info(f"Running latest version: v{__version__}")
        else:
            logger.debug(f"Could not check for updates (HTTP {response.status_code})")
    except Exception as e:
        logger.debug(f"Update check failed: {e}")
