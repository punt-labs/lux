"""The persistent hub client's frame handling — dispatch, handshake, subscribe.

These exercise :class:`LuxHubClient` without a socket: the dispatch and handshake
logic are pure given a raw frame, so they run under ``asyncio.run`` against
hand-built frames. The live end-to-end loop against a real luxd is covered by the
WebSocket end-to-end test.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

import pytest

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.hub_client import LuxHubClient
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
