"""Linux fallback discovery merges existing fonts and tolerates absent assets."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from punt_lux.display.terminal import font

_MENLO = "/System/Library/Fonts/Menlo.ttc"  # mono cover for U+276F prompt ornament
_ARIAL = "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"


def test_menlo_precedes_proportional_arial_for_mono_ornaments() -> None:
    """Menlo supplies the monospace prompt ornament (U+276F) absent from the

    base fonts, and must merge before the proportional Arial Unicode so its
    fixed-width glyph wins the fallback race.
    """
    paths = [path for path, _color in font._FALLBACKS]
    assert _MENLO in paths, "Menlo fallback dropped; U+276F renders as tofu"
    assert paths.index(_MENLO) < paths.index(_ARIAL)


@pytest.mark.parametrize("fallbacks", [False, True])
def test_terminal_font_merges_only_existing_linux_fallbacks(fallbacks: bool) -> None:
    available = {str(font._MONO)}
    linux = {path for path, _color in font._FALLBACKS if path.startswith("/usr/")}
    assert linux
    if fallbacks:
        available.update(linux)
    atlas = Mock()

    def exists(path: Path) -> bool:
        return str(path) in available

    with (
        patch(
            "punt_lux.display.terminal.font.Path.exists",
            exists,
        ),
        patch(
            "punt_lux.display.terminal.font.imgui.get_io",
            return_value=Mock(fonts=atlas),
        ),
        patch("punt_lux.display.terminal.font.imgui.ImFontConfig", side_effect=Mock),
        patch.object(font.TerminalFont, "font"),
    ):
        font.TerminalFont.load()
    paths = [call.args[0] for call in atlas.add_font_from_file_ttf.call_args_list]
    assert paths[0] == str(font._MONO)
    assert set(paths[1:]) == (linux if fallbacks else set())
    for call in atlas.add_font_from_file_ttf.call_args_list[1:]:
        config = call.args[2]
        assert config.merge_mode
        if "Emoji" in call.args[0]:
            assert config.font_loader_flags == font._FREETYPE_LOAD_COLOR


def test_missing_primary_font_leaves_ui_font_in_place() -> None:
    with (
        patch("punt_lux.display.terminal.font.Path.exists", return_value=False),
        patch("punt_lux.display.terminal.font.imgui.get_io") as get_io,
    ):
        font.TerminalFont.load()
    get_io.assert_not_called()
