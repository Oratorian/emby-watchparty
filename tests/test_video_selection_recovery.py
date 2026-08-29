"""The selection loading screen must never be the last thing a party sees.

`_restart_video_from_beginning` publishes a pending selection and tears the
outgoing video down *before* it talks to the media server, so the room is
already committed by the time anything can go wrong. Two consequences the
suite could not see:

  - The teardown runs `clear_video_state`, which also disarms
    `auto_play_after_ready`. Binge auto-advance arms that flag immediately
    before calling the restart, so the restart disarmed the flag its own
    caller had just set and every episode landed paused. Nothing on screen
    says this went wrong; the next episode is simply sitting there.
  - Any exit that leaves the selection in `preparing` strands the room. The
    video area renders the loading screen off `pending_video_selection`, the
    library button is disabled while it is set, and `sync_state` replays it
    to anyone who reloads, so the party cannot recover on its own.
"""

from __future__ import annotations

import ast
import asyncio
import pathlib

import httpx

from backend.app import create_app
from backend.src.config import Config, EnvConfig, RuntimeConfig
from backend.src.domain import PendingVideoSelection
from tests.support.asgi import asgi_client
from tests.support.credentials import TEST_SESSION_SECRET
from tests.support.fake_emby import FakeEmbyState, create_fake_emby_app


def _app(tmp_path):
    config = Config(
        EnvConfig(
            WATCH_PARTY_BIND="127.0.0.1",
            WATCH_PARTY_PORT=5000,
            APP_PREFIX="",
            SESSION_EXPIRY=3600,
            MEDIA_SERVER_TYPE="emby",
            MEDIA_SERVER_URL="http://emby.test",
            MEDIA_SERVER_API_KEY="fake-api-key",
            APP_ENV="development",
            SESSION_SECRET=TEST_SESSION_SECRET,
            SESSION_COOKIE_SECURE=False,
            CORS_ALLOWED_ORIGINS=("*",),
            TRUSTED_PROXY_CIDRS=(),
            ENABLE_HLS_TOKEN_VALIDATION=False,
        ),
        RuntimeConfig(LOG_TO_FILE=False, BINGE_WATCH_ENABLED=True),
    )
    return create_app(
        config=config,
        project_root=tmp_path,
        enable_update_check=False,
        http_transport=httpx.ASGITransport(app=create_fake_emby_app(FakeEmbyState())),
    )


async def _hosted_party(client: httpx.AsyncClient, app):
    """Create a party, become host, and register one live socket sid."""
    created = await client.post(
        "/api/party/create", json={"client_id": "client-1", "display_name": "Alice"}
    )
    party_id = created.json()["party_id"]
    await client.post(
        f"/api/party/{party_id}/join",
        json={"client_id": "client-1", "display_name": "Alice"},
    )
    login = await client.post(
        "/api/v2/auth/login", json={"username": "Alice", "password": "secret"}
    )
    assert login.json()["success"] is True
    party = app.state.party_manager.get(party_id)
    assert party is not None
    # A restart builds one stream per live sid, so the party needs at least
    # one or every selection lands in the "nobody could start" branch.
    party.sid_client_ids["socket-1"] = "client-1"
    return party_id, party


def test_binge_auto_play_survives_the_selection_teardown(tmp_path) -> None:
    """The regression: the restart disarmed the flag auto-advance had just set.

    Asserted through the real `restart_video_from_beginning` the socket layer
    exposes rather than against `clear_video_state` directly, because the
    defect was never inside that function -- it was that the restart path
    reached it at all.
    """
    app = _app(tmp_path)

    async def exercise() -> None:
        async with asgi_client(app) as client:
            party_id, party = await _hosted_party(client, app)
            restart = app.state.socket_context["restart_video_from_beginning"]

            # Exactly what _auto_advance_watchdog does, in the same order.
            await app.state.party_manager.set_auto_play_after_ready(party_id, True)
            assert party.auto_play_after_ready is True

            await restart(
                party,
                party_id,
                "client-1",
                "movie-1",
                "Fake Movie",
                "",
                item_type_hint="Episode",
            )

            assert party.auto_play_after_ready is True, (
                "the restart disarmed the auto-play flag its caller had just set, "
                "so binge auto-advance stops on a paused first frame"
            )

    asyncio.run(exercise())


def test_a_stop_still_disarms_auto_play(tmp_path) -> None:
    """The preserve flag is opt-in: only a caller installing the next video
    passes it. A stop or dissolve must still leave the party unarmed, or a
    later manual pick would start playing without anyone pressing play."""
    app = _app(tmp_path)

    async def exercise() -> None:
        async with asgi_client(app) as client:
            party_id, party = await _hosted_party(client, app)

            await app.state.party_manager.set_auto_play_after_ready(party_id, True)
            await app.state.party_manager.clear_video_state(party_id)

            assert party.auto_play_after_ready is False

    asyncio.run(exercise())


def test_only_the_replacement_path_preserves_auto_play() -> None:
    """Exactly one caller may pass preserve_auto_play.

    Structural on purpose. The behavioural test above passes just as happily
    if the flag is preserved *everywhere*, and preserving it in stop_video,
    cancel_video_selection or video_ended is the more dangerous mistake: the
    party keeps a live auto-play arming across a stop, and the next manual
    pick starts playing on its own without anyone pressing play. That is
    invisible until it happens to a room, so pin the call sites instead.
    """
    source = pathlib.Path("backend/src/socket_handlers/playback.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    preserving = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "clear_video_state"
        and any(kw.arg == "preserve_auto_play" for kw in node.keywords)
    ]

    assert len(preserving) == 1, (
        f"expected exactly one preserve_auto_play call site, found {len(preserving)} "
        f"at lines {preserving}; only the path that installs the next video may keep "
        "the flag armed"
    )
    enclosing = [
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef)
        and node.lineno <= preserving[0] <= (node.end_lineno or node.lineno)
    ]
    assert "_prepare_video_selection" in enclosing, (
        f"preserve_auto_play moved out of the selection path into {enclosing}"
    )


def _capture_emits(app) -> list[tuple]:
    """Record outbound socket emits instead of trying to deliver them."""
    sio = app.state.socket_context["sio"]
    sent: list[tuple] = []

    async def record(event, data=None, **kwargs):
        sent.append((event, data, kwargs))

    sio.emit = record
    return sent


def _handler(app, event):
    return app.state.socket_context["sio"].handlers["/"][event]


def test_the_host_can_clear_a_failed_selection_its_selector_abandoned(tmp_path) -> None:
    """The party-bricking case: a pick fails, the selector closes their tab.

    Nothing expires pending_video_selection, sync_state replays it on every
    join, and the video area disables the library while it is set, so before
    this the room stayed on the failure screen for good, reload included.
    """
    app = _app(tmp_path)

    async def exercise() -> None:
        async with asgi_client(app) as client:
            party_id, party = await _hosted_party(client, app)
            restart = app.state.socket_context["restart_video_from_beginning"]

            async def no_sources(*_args, **_kwargs):
                return {}

            app.state.socket_context["emby_client"].get_playback_info = no_sources
            # Bob picks the video, and it fails.
            party.sid_client_ids["socket-bob"] = "client-bob"
            await restart(party, party_id, "client-bob", "movie-1", "Fake Movie", "")
            failed = party.pending_video_selection
            assert failed is not None
            assert failed.status == "failed"

            # Bob leaves. Alice, the host, is all that is left.
            party.sid_client_ids.pop("socket-bob")
            assert party.host_client_id == "client-1"

            sent = _capture_emits(app)
            await _handler(app, "cancel_video_selection")(
                "socket-1", {"party_id": party_id, "selection_id": failed.selection_id}
            )

            assert party.pending_video_selection is None, (
                "the host could not clear an abandoned failed selection, "
                "so the room is stuck on the failure screen"
            )
            assert any(event == "video_selection_cancelled" for event, _, _ in sent)
            assert not any(event == "error" for event, _, _ in sent)

    asyncio.run(exercise())


def test_a_bystander_cannot_cancel_while_the_selector_is_still_there(tmp_path) -> None:
    """Widening who may act must not become "anyone may cancel anyone's pick"."""
    app = _app(tmp_path)

    async def exercise() -> None:
        async with asgi_client(app) as client:
            party_id, party = await _hosted_party(client, app)
            restart = app.state.socket_context["restart_video_from_beginning"]

            async def no_sources(*_args, **_kwargs):
                return {}

            app.state.socket_context["emby_client"].get_playback_info = no_sources
            party.sid_client_ids["socket-bob"] = "client-bob"
            await restart(party, party_id, "client-bob", "movie-1", "Fake Movie", "")
            failed = party.pending_video_selection
            assert failed is not None

            # Carol is neither the selector nor the host, and Bob is still here.
            party.sid_client_ids["socket-carol"] = "client-carol"
            party.host_client_id = "client-bob"

            sent = _capture_emits(app)
            await _handler(app, "cancel_video_selection")(
                "socket-carol", {"party_id": party_id, "selection_id": failed.selection_id}
            )

            assert party.pending_video_selection is not None
            assert any(event == "error" for event, _, _ in sent)

    asyncio.run(exercise())


def test_dismissing_a_partial_failure_does_not_stop_the_film_for_everyone_else(
    tmp_path,
) -> None:
    """A partial failure leaves the room playing and one viewer on an error.

    Cancel used to look only at pending_video_selection, so giving up on the
    stored retry offer answered "Cannot cancel this video selection" and the
    offer stayed forever. Wiring it to the retry offer has to stop short of
    the teardown the pending case does: the video is still playing for
    everyone whose stream started, and dropping a retry offer must not stop
    the film for them.

    The stranded viewer's own way out is client-side and needs no server
    authority, so it is not this event's job. See the frontend test for the
    dismiss action they get.
    """
    app = _app(tmp_path)

    async def exercise() -> None:
        async with asgi_client(app) as client:
            party_id, party = await _hosted_party(client, app)
            restart = app.state.socket_context["restart_video_from_beginning"]

            party.sid_client_ids["socket-bob"] = "client-bob"
            assert await restart(party, party_id, "client-1", "movie-1", "Fake Movie", "")
            assert party.current_video is not None

            # Exactly what the partial-failure branch leaves behind.
            stranded = PendingVideoSelection(
                selection_id="selection-partial",
                item_id="movie-1",
                title="Fake Movie",
                selected_by="client-1",
                selected_by_username="Alice",
                status="failed",
                error="Some viewers could not start this video.",
            )
            await app.state.party_manager.remember_video_selection_retry(party_id, stranded)

            sent = _capture_emits(app)
            await _handler(app, "cancel_video_selection")(
                "socket-1", {"party_id": party_id, "selection_id": "selection-partial"}
            )

            assert not any(event == "error" for event, _, _ in sent), (
                "the selector could not give up on a partial failure's retry offer"
            )
            assert party.retryable_video_selection is None
            assert party.current_video is not None, (
                "dismissing one viewer's failure stopped the video for the whole room"
            )
            cancelled = [data for event, data, _ in sent if event == "video_selection_cancelled"]
            assert cancelled
            assert cancelled[0]["cleared_video"] is False

    asyncio.run(exercise())


def test_a_crash_mid_preparation_leaves_a_failed_selection_not_a_stuck_one(tmp_path) -> None:
    """An exception after the loading screen is published must not strand the room.

    Before the fix the selection stayed in `preparing` with no event emitted:
    every member sat on the loading screen with the library disabled, and a
    reload replayed the same state out of sync_state.
    """
    app = _app(tmp_path)

    async def exercise() -> None:
        async with asgi_client(app) as client:
            party_id, party = await _hosted_party(client, app)
            restart = app.state.socket_context["restart_video_from_beginning"]

            async def explode(*_args, **_kwargs):
                raise RuntimeError("provider blew up mid-preparation")

            app.state.socket_context["emby_client"].get_playback_info = explode

            ok = await restart(party, party_id, "client-1", "movie-1", "Fake Movie", "")

            assert ok is False
            pending = party.pending_video_selection
            assert pending is not None, "the selection was dropped without telling the room"
            assert pending.status == "failed", (
                f"selection left in {pending.status!r}; the room is stuck on the loading screen"
            )
            assert pending.error

    asyncio.run(exercise())


def test_a_media_server_refusal_leaves_a_failed_selection(tmp_path) -> None:
    """The ordinary failure: the server answers, but with nothing playable."""
    app = _app(tmp_path)

    async def exercise() -> None:
        async with asgi_client(app) as client:
            party_id, party = await _hosted_party(client, app)
            restart = app.state.socket_context["restart_video_from_beginning"]

            async def no_sources(*_args, **_kwargs):
                return {}

            app.state.socket_context["emby_client"].get_playback_info = no_sources

            ok = await restart(party, party_id, "client-1", "movie-1", "Fake Movie", "")

            assert ok is False
            assert party.pending_video_selection is not None
            assert party.pending_video_selection.status == "failed"

    asyncio.run(exercise())
