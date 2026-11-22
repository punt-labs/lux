"""Control JSON preserves bounded objects and refuses malformed payloads."""

from __future__ import annotations

import pytest

from punt_lux.protocol.pty.control_fields import ControlError
from punt_lux.protocol.pty.control_json import MAX_CONTROL_BYTES, ControlJson


@pytest.mark.parametrize("fields", [{}, {"label": "Büro ☕", "id": 1}])
def test_control_json_round_trip(fields: dict[str, object]) -> None:
    assert ControlJson.parse(ControlJson.dump(fields)) == fields


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"not json",
        b"[]",
        b"null",
        b"7",
        b"\xff",
        b'{"id":1,"id":2}',
        b'{"id":NaN}',
        b" " * (MAX_CONTROL_BYTES + 1),
    ],
)
def test_malformed_control_json_rejected(data: bytes) -> None:
    with pytest.raises(ControlError):
        ControlJson.parse(data)


def test_control_json_dump_refuses_oversize_payload() -> None:
    with pytest.raises(ControlError, match="size limit"):
        ControlJson.dump({"label": "x" * MAX_CONTROL_BYTES})


def test_control_json_dump_refuses_nonfinite_numbers() -> None:
    with pytest.raises(ValueError):
        ControlJson.dump({"value": float("nan")})
