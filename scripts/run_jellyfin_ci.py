"""Start, verify, and clean an isolated real-Jellyfin CI environment."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def _run(*args: str) -> str:
    return subprocess.run(  # noqa: S603 - fixed CI commands, never shell-expanded
        args, check=True, text=True, capture_output=True
    ).stdout.strip()


def _request(
    url: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    token: str | None = None,
) -> tuple[int, object | None]:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Only HTTP(S) Jellyfin URLs are allowed")
    data = json.dumps(body).encode() if body is not None else None
    headers = {
        "Content-Type": "application/json",
        "X-Emby-Authorization": (
            'MediaBrowser Client="emby-watchparty-ci", Device="CI", '
            'DeviceId="emby-watchparty-jellyfin-ci", Version="1"'
        ),
    }
    if token:
        headers["X-Emby-Token"] = token
    request = urllib.request.Request(  # noqa: S310 - scheme and host validated above
        url, data=data, headers=headers, method=method
    )

    def decode(payload: bytes) -> object | None:
        if not payload:
            return None
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            return payload.decode("utf-8", errors="replace")

    try:
        with urllib.request.urlopen(  # noqa: S310 - request URL validated above
            request, timeout=10
        ) as response:
            payload = response.read()
            return response.status, decode(payload)
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        return exc.code, decode(payload)


def _wait(url: str, timeout: float = 120) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            status, payload = _request(url)
            if status < 500 and isinstance(payload, dict):
                return
        except OSError:
            pass
        time.sleep(2)
    raise RuntimeError(f"Timed out waiting for {url}")


def _post_ok(url: str, body: dict) -> None:
    status, payload = _request(url, method="POST", body=body)
    if status not in {200, 204}:
        raise RuntimeError(f"Jellyfin setup endpoint failed ({status}): {payload!r}")


def _configure_startup(base: str) -> None:
    _wait(f"{base}/Startup/Configuration")
    _post_ok(
        f"{base}/Startup/Configuration",
        {"UICulture": "en-US", "MetadataCountryCode": "US", "PreferredMetadataLanguage": "en"},
    )
    status, payload = _request(f"{base}/Startup/User")
    if status != 200:
        raise RuntimeError(f"Jellyfin startup user initialization failed ({status}): {payload!r}")
    _post_ok(f"{base}/Startup/User", {"Name": "Alice", "Password": "password"})
    _post_ok(
        f"{base}/Startup/RemoteAccess",
        {"EnableRemoteAccess": True, "EnableAutomaticPortMapping": False},
    )
    _post_ok(f"{base}/Startup/Complete", {})


def _create_api_key(base: str, admin_token: str) -> str:
    app_name = "emby-watchparty-ci"
    query = urllib.parse.urlencode({"app": app_name})
    status, _ = _request(f"{base}/Auth/Keys?{query}", method="POST", token=admin_token)
    if status not in {200, 204}:
        raise RuntimeError(f"Jellyfin API key creation failed ({status})")
    status, payload = _request(f"{base}/Auth/Keys", token=admin_token)
    items = payload.get("Items") if isinstance(payload, dict) else None
    if status != 200 or not isinstance(items, list):
        raise RuntimeError(f"Jellyfin API key lookup failed ({status})")
    for item in reversed(items):
        if isinstance(item, dict) and item.get("AppName") == app_name and item.get("AccessToken"):
            return str(item["AccessToken"])
    raise RuntimeError("Jellyfin did not return the created API key")


def start(args: argparse.Namespace) -> None:
    work = args.state.parent
    media = work / "media"
    config = work / "config"
    cache = work / "cache"
    for path in (media, config, cache):
        path.mkdir(parents=True, exist_ok=True)
    args.state.write_text(
        json.dumps(
            {
                "work": str(work),
                "network": args.network,
                "containers": [args.app_name, args.jellyfin_name],
            }
        ),
        encoding="utf-8",
    )
    video = media / "Synthetic HLS.mp4"
    _run(
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "testsrc2=size=640x360:rate=24",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000",
        "-t",
        "30",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-metadata",
        "title=Synthetic HLS",
        "-y",
        str(video),
    )
    other_video = media / "Other Movie.mp4"
    shutil.copyfile(video, other_video)
    (media / "Synthetic HLS.nfo").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<movie>
  <title>Synthetic HLS</title>
  <year>2020</year>
  <mpaa>PG-13</mpaa>
  <genre>Journey Genre</genre>
  <studio>Journey Studio</studio>
</movie>
""",
        encoding="utf-8",
    )
    (media / "Other Movie.nfo").write_text(
        """<?xml version="1.0" encoding="utf-8"?>
<movie>
  <title>Other Movie</title>
  <year>2021</year>
  <mpaa>R</mpaa>
  <genre>Other Genre</genre>
  <studio>Other Studio</studio>
</movie>
""",
        encoding="utf-8",
    )
    _run("docker", "network", "create", args.network)
    _run(
        "docker",
        "run",
        "--detach",
        "--name",
        args.jellyfin_name,
        "--network",
        args.network,
        "--network-alias",
        "jellyfin",
        "--publish",
        f"{args.jellyfin_port}:8096",
        "--volume",
        f"{config.resolve()}:/config",
        "--volume",
        f"{cache.resolve()}:/cache",
        "--volume",
        f"{media.resolve()}:/media:ro",
        args.jellyfin_image,
    )
    base = f"http://127.0.0.1:{args.jellyfin_port}"
    _wait(f"{base}/System/Info/Public")
    _configure_startup(base)
    status, auth = _request(
        f"{base}/Users/AuthenticateByName",
        method="POST",
        body={"Username": "Alice", "Pw": "password"},
    )
    if status != 200 or not isinstance(auth, dict):
        raise RuntimeError(f"Jellyfin authentication failed ({status})")
    token = str(auth["AccessToken"])
    user_id = str(auth["User"]["Id"])
    api_key = _create_api_key(base, token)
    query = urllib.parse.urlencode(
        {"name": "Movies", "collectionType": "movies", "paths": "/media", "refreshLibrary": "true"}
    )
    status, _ = _request(f"{base}/Library/VirtualFolders?{query}", method="POST", token=token)
    if status not in {200, 204}:
        raise RuntimeError(f"Jellyfin library creation failed ({status})")
    deadline = time.monotonic() + 180
    synthetic_item: dict | None = None
    while time.monotonic() < deadline:
        item_query = urllib.parse.urlencode({"Recursive": "true", "IncludeItemTypes": "Movie"})
        status, payload = _request(f"{base}/Users/{user_id}/Items?{item_query}", token=token)
        items = payload.get("Items") if isinstance(payload, dict) else None
        if status == 200 and isinstance(items, list) and len(items) >= 2:
            synthetic_item = next(
                (
                    item
                    for item in items
                    if isinstance(item, dict) and item.get("Name") == "Synthetic HLS"
                ),
                None,
            )
            if synthetic_item:
                detail_status, details = _request(
                    f"{base}/Users/{user_id}/Items/{synthetic_item['Id']}", token=token
                )
                if (
                    detail_status == 200
                    and isinstance(details, dict)
                    and "Journey Genre" in details.get("Genres", [])
                    and details.get("ProductionYear") == 2020
                    and details.get("OfficialRating") == "PG-13"
                    and any(
                        studio.get("Name") == "Journey Studio"
                        for studio in details.get("Studios", [])
                        if isinstance(studio, dict)
                    )
                ):
                    break
        time.sleep(3)
    else:
        raise RuntimeError("Jellyfin library scan did not discover scoped-filter fixtures")
    item_id = str(synthetic_item["Id"])
    for path in (
        f"/Users/{user_id}/FavoriteItems/{item_id}",
        f"/Users/{user_id}/PlayedItems/{item_id}",
    ):
        status, _ = _request(f"{base}{path}", method="POST", token=token)
        if status not in {200, 204}:
            raise RuntimeError(f"Jellyfin user-state fixture failed ({status})")
    env_file = work / "app.env"
    env_file.write_text(
        "\n".join(
            (
                "APP_ENV=development",
                "MEDIA_SERVER_TYPE=jellyfin",
                "JELLYFIN_SERVER_URL=http://jellyfin:8096",
                f"JELLYFIN_API_KEY={api_key}",
                "SESSION_SECRET=jellyfin-ci-session-secret-at-least-32-characters",
                "SESSION_COOKIE_SECURE=false",
            )
        ),
        encoding="utf-8",
    )
    _run(
        "docker",
        "run",
        "--detach",
        "--name",
        args.app_name,
        "--network",
        args.network,
        "--publish",
        f"{args.app_port}:5000",
        "--env-file",
        str(env_file.resolve()),
        args.app_image,
    )
    _wait(f"http://127.0.0.1:{args.app_port}/api/ready")
    args.state.write_text(
        json.dumps(
            {
                "work": str(work),
                "network": args.network,
                "containers": [args.app_name, args.jellyfin_name],
                "base": base,
                "token": token,
            }
        ),
        encoding="utf-8",
    )


def verify(args: argparse.Namespace) -> None:
    state = json.loads(args.state.read_text(encoding="utf-8"))
    status, sessions = _request(f"{state['base']}/Sessions", token=state["token"])
    if status != 200 or not isinstance(sessions, list):
        raise RuntimeError(f"Could not inspect Jellyfin sessions ({status})")
    if any(session.get("NowPlayingItem") for session in sessions if isinstance(session, dict)):
        raise RuntimeError("Jellyfin still reports active playback after Stop Video")


def cleanup(args: argparse.Namespace) -> None:
    if not args.state.exists():
        return
    state = json.loads(args.state.read_text(encoding="utf-8"))
    for container in state.get("containers", []):
        subprocess.run(  # noqa: S603 - isolated CI state, no shell
            ["docker", "rm", "--force", container],  # noqa: S607
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    subprocess.run(  # noqa: S603 - isolated CI state, no shell
        ["docker", "network", "rm", state["network"]],  # noqa: S607
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    shutil.rmtree(state["work"], ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("start", "verify", "cleanup"))
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--jellyfin-image", default="jellyfin/jellyfin:10.11.11")
    parser.add_argument("--app-image", default="emby-watchparty:jellyfin-ci")
    parser.add_argument("--network", default="watchparty-jellyfin-ci")
    parser.add_argument("--jellyfin-name", default="jellyfin-ci")
    parser.add_argument("--app-name", default="watchparty-jellyfin-ci")
    parser.add_argument("--jellyfin-port", type=int, default=8097)
    parser.add_argument("--app-port", type=int, default=5013)
    args = parser.parse_args()
    {"start": start, "verify": verify, "cleanup": cleanup}[args.command](args)


if __name__ == "__main__":
    main()
