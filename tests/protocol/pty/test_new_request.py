"""NewRequest names a launcher, never a command line, and round-trips."""

from __future__ import annotations

import json

import pytest

from punt_lux.protocol.pty.control import ControlCodec, ControlRequest
from punt_lux.protocol.pty.control_fields import ControlError
from punt_lux.protocol.pty.new_request import NewRequest


@pytest.mark.parametrize(
    "message",
    [
        NewRequest(1),
        NewRequest(2, "work", "claude", 120, 40),
        NewRequest(3, "Terminal 3", "tail build log"),
    ],
)
def test_new_request_round_trips(message: NewRequest) -> None:
    assert isinstance(message, ControlRequest)
    assert ControlCodec.decode(ControlCodec.encode(message)) == message
    assert NewRequest.from_dict(message.to_dict()) == message


def test_the_default_launcher_is_the_login_shell() -> None:
    assert NewRequest(1).launcher == ""


def test_the_wire_form_names_a_launcher_and_carries_no_command() -> None:
    fields = NewRequest(1, "work", "claude").to_dict()
    assert fields["launcher"] == "claude"
    assert "command" not in fields


def _new(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "id": 1,
        "op": "new",
        "label": "a",
        "launcher": "",
        "cols": 80,
        "rows": 24,
    }
    fields.update(overrides)
    return fields


@pytest.mark.parametrize(
    "raw",
    [
        _new(label="x" * 65),
        _new(label="a\nb"),
        _new(label="\x9b2J"),
        _new(launcher="x" * 65),
        _new(launcher="a\x00"),
        _new(launcher="\x9b2J"),
        _new(launcher=5),
        _new(rows=513),
        _new(label=5),
        _new(cols=0),
        {k: v for k, v in _new().items() if k != "rows"},
        {k: v for k, v in _new().items() if k != "launcher"},
        _new(command="/bin/sh -c 'rm -rf ~'"),
        _new(x=1),
    ],
)
def test_malformed_new_request_rejected(raw: dict[str, object]) -> None:
    with pytest.raises(ControlError):
        ControlCodec.decode(json.dumps(raw).encode())


def test_label_and_launcher_keep_printable_unicode() -> None:
    request = NewRequest(1, "Büro ☕ 3", "Büro shell")
    assert ControlCodec.decode(ControlCodec.encode(request)) == request


def test_construction_validates() -> None:
    with pytest.raises(ControlError, match="label"):
        NewRequest(1, "x" * 65)
    with pytest.raises(ControlError, match="launcher"):
        NewRequest(1, "work", "x" * 65)
    with pytest.raises(ControlError, match="cols"):
        NewRequest(1, "work", "", 0)


def test_decoding_validates_each_field_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from punt_lux.protocol.pty.control_fields import ControlFields

    calls: list[str] = []
    original = ControlFields.shape

    def counting_shape(self: ControlFields, op: str, keys: frozenset[str]) -> None:
        calls.append(op)
        original(self, op, keys)

    monkeypatch.setattr(ControlFields, "shape", counting_shape)
    NewRequest.from_dict(NewRequest(1, "work", "claude").to_dict())
    calls.clear()
    NewRequest.from_dict(
        {"id": 1, "op": "new", "label": "w", "launcher": "", "cols": 80, "rows": 24}
    )
    assert calls == ["new"]
