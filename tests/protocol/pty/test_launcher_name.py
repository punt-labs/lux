"""LauncherName: the menu name a request may start, bounded and printable."""

from __future__ import annotations

import pytest

from punt_lux.protocol.pty.control_fields import ControlError, ControlFields
from punt_lux.protocol.pty.launcher_name import LauncherName


@pytest.mark.parametrize("text", ["", "claude", "tail build log", "Büro ☕", "x" * 64])
def test_launcher_name_accepts(text: str) -> None:
    assert LauncherName(text).text == text


@pytest.mark.parametrize("text", ["x" * 65, "a\nb", "a\x00", "\x9b2J", "\x7f"])
def test_launcher_name_refuses(text: str) -> None:
    with pytest.raises(ControlError, match="launcher"):
        LauncherName(text)


def test_requested_reads_the_launcher_field() -> None:
    assert LauncherName.requested(ControlFields({"launcher": "pi"})).text == "pi"


@pytest.mark.parametrize("raw", [{}, {"launcher": None}, {"launcher": 3}])
def test_requested_refuses_missing_or_non_string(raw: dict[str, object]) -> None:
    with pytest.raises(ControlError, match="launcher"):
        LauncherName.requested(ControlFields(raw))
