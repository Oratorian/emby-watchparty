"""Best-effort asynchronous release check."""

from backend.src import __version__


async def check_for_updates(http_client, logger) -> None:
    try:
        response = await http_client.get(
            "https://api.github.com/repos/Oratorian/emby-watchparty/releases/latest",
            timeout=5,
        )
        if response.status_code != 200:
            logger.debug("Could not check for updates (HTTP %s)", response.status_code)
            return
        data = response.json()
        latest = data.get("tag_name", "").lstrip("v")
        if latest and latest != __version__:
            logger.info("Update available: v%s (current: v%s)", latest, __version__)
        else:
            logger.info("Running latest version: v%s", __version__)
    except Exception as exc:
        logger.debug("Update check failed: %s", exc)
