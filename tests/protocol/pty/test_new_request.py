"""New terminal requests validate labels, commands and initial sizes."""

from __future__ import annotations

import pytest

from punt_lux.protocol.pty.control_fields import ControlError
from punt_lux.protocol.pty.new_request import NewRequest


@pytest.mark.parametrize(
    "request_",
    [
        NewRequest(1),
        NewRequest(2, "work", "/bin/zsh -l", 120, 40),
        NewRequest(3, "Terminal 3"),
    ],
)
def test_new_request_round_trip(request_: NewRequest) -> None:
    assert NewRequest.from_dict(request_.to_dict()) == request_


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
    ],
)
def test_malformed_new_request_rejected(raw: dict[str, object]) -> None:
    with pytest.raises(ControlError):
        NewRequest.from_dict(raw)


def test_label_keeps_printable_unicode() -> None:
    request = NewRequest(1, "Büro ☕ 3")
    assert NewRequest.from_dict(request.to_dict()) == request


def test_new_request_construction_validates() -> None:
    with pytest.raises(ControlError, match="label"):
        NewRequest(1, "x" * 65)
    with pytest.raises(ControlError, match="cols"):
        NewRequest(1, "work", "", 0)
