"""UI discovery must not prevent the bundled terminal font from loading."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from punt_lux.display.fonts import FontLoader


@pytest.mark.parametrize("primary", [None, "/fonts/ui.ttf"])
def test_terminal_font_loads_with_or_without_a_system_ui_font(
    primary: str | None,
) -> None:
    with (
        patch.object(FontLoader, "_find", return_value=(primary, [])),
        patch("imgui_bundle.hello_imgui.load_font") as load_ui,
        patch.object(FontLoader, "_load_terminal_font") as load_terminal,
    ):
        FontLoader().load()
    load_terminal.assert_called_once_with()
    assert load_ui.call_count == (0 if primary is None else 1)


def test_ui_fallbacks_load_before_the_independent_terminal_font() -> None:
    events: list[str] = []

    def record_ui_font(path: str, *_args: object) -> None:
        events.append(path)

    with (
        patch.object(FontLoader, "_find", return_value=("ui.ttf", ["symbols.ttf"])),
        patch(
            "imgui_bundle.hello_imgui.load_font",
            side_effect=record_ui_font,
        ),
        patch.object(
            FontLoader, "_load_terminal_font", side_effect=lambda: events.append("mono")
        ),
    ):
        FontLoader().load()
    assert events == ["ui.ttf", "symbols.ttf", "mono"]
