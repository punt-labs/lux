"""Control requests validate their own fields and preserve typed round-trips."""

from __future__ import annotations

import json
from typing import Literal

import pytest

from punt_lux.protocol.pty.attach import AttachRequest
from punt_lux.protocol.pty.control import (
    WIRE_VERSION,
    ControlCodec,
    ControlRequest,
    Request,
)
from punt_lux.protocol.pty.control_fields import ControlError
from punt_lux.protocol.pty.control_json import MAX_CONTROL_BYTES
from punt_lux.protocol.pty.hello import HelloRequest
from punt_lux.protocol.pty.new_request import NewRequest
from punt_lux.protocol.pty.session_events import SessionEvent, WatchRequest
from punt_lux.protocol.pty.session_label import SessionLabel
from punt_lux.protocol.pty.session_requests import KillRequest, ListRequest


def test_wire_version_stays_compatible_with_running_daemon() -> None:
    assert WIRE_VERSION == 3


@pytest.mark.parametrize(
    "message",
    [
        HelloRequest(1, 1, "pyghostty-0.1.4"),
        AttachRequest(2, "shell-1", "/bin/zsh -l", 120, 40),
        AttachRequest(3, "other"),
        ListRequest(4),
        KillRequest(5, "shell-1"),
    ],
)
def test_all_requests_round_trip(message: Request) -> None:
    assert isinstance(message, ControlRequest)
    assert ControlCodec.decode(ControlCodec.encode(message)) == message
    assert type(message).from_dict(message.to_dict()) == message


def test_unicode_command_is_utf8_not_ascii_escape_expansion() -> None:
    request = AttachRequest(1, "shell", "/bin/echo 日本語")
    encoded = ControlCodec.encode(request)
    assert "日本語".encode() in encoded
    assert ControlCodec.decode(encoded) == request


@pytest.mark.parametrize("value", [True, False, 0, -1, 1.5, "1", 1 << 32])
def test_invalid_request_ids(value: object) -> None:
    data = json.dumps({"id": value, "op": "list"}).encode()
    with pytest.raises(ControlError, match="id"):
        ControlCodec.decode(data)


@pytest.mark.parametrize("value", ["", "x/y", "x y", "x\n", "x" * 129, 7, None])
def test_invalid_session_names(value: object) -> None:
    data = json.dumps({"id": 1, "op": "kill", "session": value}).encode()
    with pytest.raises(ControlError, match="session"):
        ControlCodec.decode(data)


@pytest.mark.parametrize(
    "key,value",
    [
        ("cols", 0),
        ("cols", 1025),
        ("cols", True),
        ("rows", 0),
        ("rows", 513),
        ("rows", "24"),
        ("command", None),
        ("command", "x" * 4097),
        ("command", "bad\x00command"),
    ],
)
def test_invalid_attach_fields(key: str, value: object) -> None:
    raw = AttachRequest(1, "shell").to_dict()
    raw[key] = value
    with pytest.raises(ControlError, match=key):
        ControlCodec.decode(json.dumps(raw).encode())


@pytest.mark.parametrize(
    "raw",
    [
        {"id": 1, "op": "unknown"},
        {"op": "list"},
        {"id": 1, "op": "list", "extra": 5},
        {"id": 1, "op": "kill"},
    ],
)
def test_unknown_operation_missing_or_extra_fields(raw: dict[str, object]) -> None:
    with pytest.raises(ControlError):
        ControlCodec.decode(json.dumps(raw).encode())


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"not json",
        b"[]",
        b"null",
        b"7",
        b"\xff",
        b'{"id":1,"id":2,"op":"list"}',
        b'{"id":NaN,"op":"list"}',
        b" " * (MAX_CONTROL_BYTES + 1),
    ],
)
def test_malformed_control_input(data: bytes) -> None:
    with pytest.raises(ControlError):
        ControlCodec.decode(data)


def test_direct_construction_validates_too() -> None:
    with pytest.raises(ControlError):
        AttachRequest(1, "invalid/name")
    with pytest.raises(ControlError):
        ListRequest(0)
    with pytest.raises(ControlError):
        HelloRequest(1, 0, "snapshot-version")


@pytest.mark.parametrize(
    "message",
    [
        NewRequest(1),
        NewRequest(2, "work", "/bin/zsh -l", 120, 40),
        NewRequest(3, "Terminal 3"),
        WatchRequest(4),
    ],
)
def test_new_and_watch_round_trip(message: Request) -> None:
    assert isinstance(message, ControlRequest)
    assert ControlCodec.decode(ControlCodec.encode(message)) == message
    assert type(message).from_dict(message.to_dict()) == message


@pytest.mark.parametrize("kind", ["created", "ended"])
def test_session_event_round_trip(kind: Literal["created", "ended"]) -> None:
    event = SessionEvent(kind, "t1.2", "work")
    assert SessionEvent.decode(event.encode()) == event
    assert SessionEvent.from_dict(event.to_dict()) == event


@pytest.mark.parametrize(
    "raw",
    [
        {
            "id": 1,
            "op": "new",
            "label": "x" * 65,
            "command": "",
            "cols": 80,
            "rows": 24,
        },
        {"id": 1, "op": "new", "label": "a\nb", "command": "", "cols": 80, "rows": 24},
        {
            "id": 1,
            "op": "new",
            "label": "\x9b2J",
            "command": "",
            "cols": 80,
            "rows": 24,
        },
        {"id": 1, "op": "new", "label": "a", "command": "\x00", "cols": 80, "rows": 24},
        {"id": 1, "op": "new", "label": "a", "command": "", "cols": 80, "rows": 513},
        {"id": 1, "op": "new", "label": 5, "command": "", "cols": 80, "rows": 24},
        {"id": 1, "op": "new", "label": "a", "command": "", "cols": 0, "rows": 24},
        {"id": 1, "op": "new", "label": "a", "command": "", "cols": 80},
        {
            "id": 1,
            "op": "new",
            "label": "a",
            "command": "",
            "cols": 80,
            "rows": 24,
            "x": 1,
        },
        {"id": 1, "op": "watch", "extra": 1},
        {"op": "watch"},
    ],
)
def test_malformed_new_and_watch_rejected(raw: dict[str, object]) -> None:
    with pytest.raises(ControlError):
        ControlCodec.decode(json.dumps(raw).encode())


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


def test_session_event_is_not_a_request() -> None:
    event = SessionEvent("created", "t1.2", "work")
    with pytest.raises(ControlError, match="operation"):
        ControlCodec.decode(event.encode())


def test_label_keeps_printable_unicode() -> None:
    request = NewRequest(1, "Büro ☕ 3")
    assert ControlCodec.decode(ControlCodec.encode(request)) == request


def test_new_watch_and_event_construction_validates() -> None:
    with pytest.raises(ControlError, match="label"):
        NewRequest(1, "x" * 65)
    with pytest.raises(ControlError, match="cols"):
        NewRequest(1, "work", "", 0)
    with pytest.raises(ControlError, match="id"):
        WatchRequest(0)
    with pytest.raises(ControlError, match="session"):
        SessionEvent("ended", "bad/id", "work")
    with pytest.raises(ControlError, match="label"):
        SessionEvent("created", "t1.2", "")


@pytest.mark.parametrize("text", ["", "work", "Büro ☕", "x" * 64])
def test_session_label_accepts(text: str) -> None:
    assert SessionLabel(text).text == text


@pytest.mark.parametrize("text", ["x" * 65, "a\nb", "a\x00", "\x9b2J", "\x7f"])
def test_session_label_refuses(text: str) -> None:
    with pytest.raises(ControlError, match="label"):
        SessionLabel(text)
