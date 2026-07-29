"""The persistent hub client's frame handling — dispatch, handshake, subscribe.

These exercise :class:`LuxHubClient` without a socket: the dispatch and handshake
logic are pure given a raw frame, so they run under ``asyncio.run`` against
hand-built frames. The live end-to-end loop against a real luxd is covered by the
WebSocket end-to-end test.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping

import pytest
import websockets

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.hub_client import LuxHubClient
from punt_lux.hub_paths import HubPaths
from punt_lux.identity_headers import ClientHeaders
from punt_lux.protocol.messages.listen import (
    CallbackFrame,
    EventFrame,
    ReadyFrame,
    SubscribeFrame,
)


def _identity() -> ClientIdentity:
    return ClientIdentity(kind="app", name="voxd", repo="/w/vox")


def _noop_callback(_callback_id: str) -> None:
    return None


def _noop_event(_topic: str, _payload: Mapping[str, object]) -> None:
    return None


def _client(
    *,
    on_callback: object = _noop_callback,
    on_event: object = _noop_event,
) -> LuxHubClient:
    return LuxHubClient(
        "ws://127.0.0.1:0/ws",
        _identity(),
        on_callback=on_callback,  # type: ignore[arg-type]  # handler protocol; test doubles satisfy it
        on_event=on_event,  # type: ignore[arg-type]
    )


def _reresolve_client(url: str = "ws://127.0.0.1:0/ws") -> LuxHubClient:
    """A client whose reconnect loop re-reads the port file (the daemon path)."""
    return LuxHubClient(
        url,
        _identity(),
        on_callback=_noop_callback,
        on_event=_noop_event,
        reresolve=True,
    )


def _reads_port(value: int | None) -> Callable[[HubPaths], int | None]:
    """A ``HubPaths.read_port`` stand-in returning a fixed port (or ``None``)."""

    def _read(_self: HubPaths) -> int | None:
        return value

    return _read


class _FakeConnection:
    """A stand-in websocket: a ready handshake, then an immediately-ended stream.

    ``recv`` returns the handshake frame and async-iteration stops at once, so a
    session runs its handshake and ``on_connect`` and returns, which drives the
    listen loop's reconnect. Reused across connects — it holds no per-session state.
    """

    async def __aenter__(self) -> _FakeConnection:
        return self

    async def __aexit__(self, *_exc: object) -> bool:
        return False

    async def recv(self) -> str:
        return ReadyFrame(connection_id="c").model_dump_json()

    async def send(self, _frame: str) -> None:
        return None

    def __aiter__(self) -> _FakeConnection:
        return self

    async def __anext__(self) -> str:
        raise StopAsyncIteration


def _client_with_on_connect(on_connect: Callable[[], None]) -> LuxHubClient:
    """A pinned client (no port file) carrying an ``on_connect`` callback."""
    return LuxHubClient(
        "ws://127.0.0.1:0/ws",
        _identity(),
        on_callback=_noop_callback,
        on_event=_noop_event,
        on_connect=on_connect,
    )


def test_a_callback_frame_dispatches_to_the_callback_handler() -> None:
    seen: list[str] = []
    client = _client(on_callback=seen.append)
    asyncio.run(client._dispatch(CallbackFrame(callback_id="beads").model_dump_json()))
    assert seen == ["beads"]


def test_an_event_frame_dispatches_topic_and_payload() -> None:
    seen: list[tuple[str, Mapping[str, object]]] = []

    def record(topic: str, payload: Mapping[str, object]) -> None:
        seen.append((topic, payload))

    client = _client(on_event=record)
    frame = EventFrame(topic="music.play", payload={"album_id": "jazz-1"})
    asyncio.run(client._dispatch(frame.model_dump_json()))
    assert seen == [("music.play", {"album_id": "jazz-1"})]


def test_an_async_handler_is_awaited() -> None:
    seen: list[str] = []

    async def handler(callback_id: str) -> None:
        seen.append(callback_id)

    client = _client(on_callback=handler)
    asyncio.run(client._dispatch(CallbackFrame(callback_id="beads").model_dump_json()))
    assert seen == ["beads"]


def test_the_handshake_frame_yields_the_connection_id() -> None:
    client = _client()
    conn = client._ready(ReadyFrame(connection_id="abc123").model_dump_json())
    assert conn == "abc123"


def test_a_non_ready_first_frame_is_a_protocol_error() -> None:
    client = _client()
    with pytest.raises(ValueError, match="ready handshake"):
        client._ready(CallbackFrame(callback_id="beads").model_dump_json())


def test_subscribe_accumulates_topics_for_the_next_connect() -> None:
    client = _client()
    client.subscribe("music.play", "music.stop")
    client.subscribe("music.play")  # a repeat is folded, not duplicated
    assert client._topics == {"music.play", "music.stop"}


def test_a_mid_stream_ready_frame_is_inert() -> None:
    # Only the handshake carries ready; a stray one mid-stream dispatches to nothing.
    calls: list[object] = []

    def record_event(topic: str, payload: Mapping[str, object]) -> None:
        calls.append((topic, payload))

    client = _client(on_callback=calls.append, on_event=record_event)
    asyncio.run(client._dispatch(ReadyFrame(connection_id="x").model_dump_json()))
    assert calls == []


def test_the_client_declares_its_identity_in_the_handshake_headers() -> None:
    # The headers the client sends are exactly REST's, so the two legs share a
    # connection: a callback registered over REST is delivered on this stream.
    client = _client()
    assert client._headers == ClientHeaders.to_wire(_identity())


def test_a_subscribe_frame_round_trips_through_the_wire() -> None:
    frame = SubscribeFrame(topics=("music.play", "music.stop"))
    assert (
        frame.model_dump_json()
        == '{"kind":"subscribe","topics":["music.play","music.stop"]}'
    )


def test_on_connect_fires_after_the_first_connect_and_again_after_a_reconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The register-fresh callback runs after every handshake, not just the first:
    # the internal reconnect restores subscriptions but not lease-expired callbacks,
    # so an app re-registers here. Each fake session ends at once, driving a clean
    # reconnect; on_connect stops the loop after the second so the test terminates.
    ids: list[str] = []

    def on_connect() -> None:
        ids.append(client.connection_id)  # set by the handshake before this runs
        if len(ids) >= 2:
            client.stop()

    client = _client_with_on_connect(on_connect)

    def _connect(*_a: object, **_k: object) -> _FakeConnection:
        return _FakeConnection()

    monkeypatch.setattr(websockets, "connect", _connect)

    asyncio.run(client.listen())

    # Fired once per handshake, and each ran after the connection id was bound.
    assert ids == ["c", "c"]


def test_a_raising_on_connect_is_isolated_and_the_listen_loop_survives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A failed register-fresh must not tear down a healthy connection: the callout
    # is logged and the session proceeds. The loop ends only because the fake
    # connection stops it, and listen() returns rather than propagating the error.
    calls: list[int] = []

    def on_connect() -> None:
        calls.append(1)
        raise RuntimeError("register-fresh failed")

    client = _client_with_on_connect(on_connect)

    def _connect(*_a: object, **_k: object) -> _FakeConnection:
        client.stop()  # end after this one session so the loop terminates
        return _FakeConnection()

    monkeypatch.setattr(websockets, "connect", _connect)

    # listen() must not raise — the RuntimeError was isolated, not propagated.
    asyncio.run(client.listen())
    assert calls == [1]


def test_a_reconnect_re_resolves_a_changed_port_file_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A luxd restart onto a new port must be followed, not backed off against
    # forever: each reconnect re-reads the port file and rebuilds the url.
    client = _reresolve_client()
    monkeypatch.setattr(HubPaths, "read_port", _reads_port(9001))
    assert client._current_url() == "ws://127.0.0.1:9001/ws"
    monkeypatch.setattr(HubPaths, "read_port", _reads_port(9002))
    assert client._current_url() == "ws://127.0.0.1:9002/ws"


def test_a_missing_port_file_yields_no_url_and_keeps_the_last_known(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _reresolve_client()
    monkeypatch.setattr(HubPaths, "read_port", _reads_port(9001))
    assert client._current_url() == "ws://127.0.0.1:9001/ws"
    # luxd goes down mid-restart: the port file is gone. No url to connect to,
    # but the last-known url is preserved so nothing is lost.
    monkeypatch.setattr(HubPaths, "read_port", _reads_port(None))
    assert client._current_url() is None
    assert client._url == "ws://127.0.0.1:9001/ws"


def test_a_pinned_client_never_re_resolves_from_the_port_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A client built with an explicit url (a test, a direct endpoint) keeps it
    # across reconnects and never consults the port file.
    client = _client()  # reresolve defaults to False
    monkeypatch.setattr(HubPaths, "read_port", _reads_port(9999))
    assert client._current_url() == "ws://127.0.0.1:0/ws"


def test_the_loop_backs_off_while_the_port_is_absent_then_connects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The reconnect loop stays alive across a missing port file and connects the
    # moment a port reappears — a restarting luxd is rejoined, not abandoned.
    client = _reresolve_client()
    reads = {"n": 0}

    def _read_port(_self: HubPaths) -> int | None:
        reads["n"] += 1
        return None if reads["n"] <= 2 else 9100  # absent twice, then a port

    connected: list[str] = []

    def _connect(url: str, **_kwargs: object) -> object:
        connected.append(url)
        client.stop()  # one attempt is enough to prove the loop reached connect
        raise OSError("no server")

    async def _no_delay(_seconds: float) -> None:
        return None

    monkeypatch.setattr(HubPaths, "read_port", _read_port)
    monkeypatch.setattr(websockets, "connect", _connect)
    monkeypatch.setattr(asyncio, "sleep", _no_delay)

    asyncio.run(client.listen())

    # Two absent reads were tolerated (loop kept going), then the reappeared port
    # was used for the one connect attempt.
    assert connected == ["ws://127.0.0.1:9100/ws"]
    assert reads["n"] == 3
