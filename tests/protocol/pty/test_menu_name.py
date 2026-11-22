"""MenuName: the shared rules for every name a terminal menu shows."""

from __future__ import annotations

import pytest

from punt_lux.protocol.pty.control_fields import ControlError
from punt_lux.protocol.pty.launcher_name import LauncherName
from punt_lux.protocol.pty.menu_name import MenuName
from punt_lux.protocol.pty.session_label import SessionLabel


@pytest.mark.parametrize("text", ["", "work", "Büro ☕", "x" * 64])
def test_menu_name_accepts(text: str) -> None:
    assert MenuName(text, "name").text == text


@pytest.mark.parametrize(
    "text", ["x" * 65, "a\nb", "a\x00", "\x9b2J", "\x7f", "\ud800"]
)
def test_menu_name_refuses(text: str) -> None:
    with pytest.raises(ControlError, match="name"):
        MenuName(text, "name")


@pytest.mark.parametrize(
    ("kind", "field"), [(SessionLabel, "label"), (LauncherName, "launcher")]
)
def test_each_kind_names_its_own_field_in_a_refusal(
    kind: type[SessionLabel | LauncherName], field: str
) -> None:
    with pytest.raises(ControlError, match=f"^{field} "):
        kind("x" * 65)
