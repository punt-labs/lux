"""Session events and watch requests preserve validated round-trips."""

from __future__ import annotations

import json
from typing import Literal

import pytest

from punt_lux.wire.stream.control import ControlCodec
from punt_lux.wire.stream.control_fields import ControlError
from punt_lux.wire.stream.new_request import NewRequest
from punt_lux.wire.stream.session_events import SessionEvent, WatchRequest


@pytest.mark.parametrize("kind", ["created", "ended"])
def test_session_event_round_trip(kind: Literal["created", "ended"]) -> None:
    event = SessionEvent(kind, "t1.2", "work")
    assert SessionEvent.decode(event.encode()) == event
    assert SessionEvent.from_dict(event.to_dict()) == event


@pytest.mark.parametrize(
    "raw",
    [
        {"event": "gone", "session": "t1.2", "label": "w"},
        {"event": "created", "session": "bad id", "label": "w"},
        {"event": "created", "session": "t1.2"},
        {"event": "ended", "session": "t1.2", "label": "w", "x": 1},
        {"event": "ended", "session": "t1.2", "label": "a\x00"},
        {"event": "ended", "session": "t1.2", "label": "a\x9b"},
        {"event": "created", "session": "t1.2", "label": ""},
        {"event": 1, "session": "t1.2", "label": "w"},
        {"op": "list", "event": "created", "session": "t1.2", "label": "w"},
    ],
)
def test_malformed_session_event_rejected(raw: dict[str, object]) -> None:
    with pytest.raises(ControlError):
        SessionEvent.decode(json.dumps(raw).encode())


def test_new_request_is_not_a_session_event() -> None:
    with pytest.raises(ControlError):
        SessionEvent.decode(ControlCodec.encode(NewRequest(1)))


def test_watch_request_round_trip() -> None:
    request = WatchRequest(4)
    assert WatchRequest.from_dict(request.to_dict()) == request


@pytest.mark.parametrize("raw", [{"id": 1, "op": "watch", "extra": 1}, {"op": "watch"}])
def test_malformed_watch_request_rejected(raw: dict[str, object]) -> None:
    with pytest.raises(ControlError):
        WatchRequest.from_dict(raw)


def test_watch_and_event_construction_validates() -> None:
    with pytest.raises(ControlError, match="id"):
        WatchRequest(0)
    with pytest.raises(ControlError, match="session"):
        SessionEvent("ended", "bad/id", "work")
    with pytest.raises(ControlError, match="label"):
        SessionEvent("created", "t1.2", "")
