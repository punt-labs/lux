"""Control requests validate their own fields and preserve typed round-trips."""

from __future__ import annotations

import json

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


def test_session_event_is_not_a_request() -> None:
    event = SessionEvent("created", "t1.2", "work")
    with pytest.raises(ControlError, match="operation"):
        ControlCodec.decode(event.encode())
