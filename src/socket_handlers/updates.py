"""
Update Checker
Standalone function to check GitHub for latest release.
"""

import requests
from src import __version__


def check_for_updates(logger):
    """Check GitHub for latest release and notify if update available"""
    try:
        # GitHub API endpoint for latest release
        github_api_url = (
            "https://api.github.com/repos/Oratorian/emby-watchparty/releases/latest"
        )
        response = requests.get(github_api_url, timeout=5)

        if response.status_code == 200:
            latest_release = response.json()
            latest_version = latest_release.get("tag_name", "").lstrip("v")

            if latest_version and latest_version != __version__:
                logger.warning("=" * 60)
                logger.warning(
                    f"UPDATE AVAILABLE: v{latest_version} (current: v{__version__})"
                )
                logger.warning(
                    f"Download: {latest_release.get('html_url', 'https://github.com/Oratorian/emby-watchparty/releases')}"
                )
                logger.warning("=" * 60)
            else:
                logger.info(f"Running latest version: v{__version__}")
        else:
            # Silently skip if GitHub API is unreachable
            logger.debug(
                f"Could not check for updates (GitHub API returned {response.status_code})"
            )
    except Exception as e:
        # Don't spam logs if update check fails
        logger.debug(f"Update check failed: {e}")
