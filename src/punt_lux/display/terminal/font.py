# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportAttributeAccessIssue=false
# pyright: reportMissingModuleSource=false, reportPrivateUsage=false
# (pyghostty is an untyped cffi binding: its ffi/lib members are unknown to pyright.)
"""The terminal's monospace font, with CJK and emoji fallbacks merged in.

A terminal needs a strictly fixed-width font; Lux's UI font (Arial Unicode)
is proportional. Inconsolata ships inside imgui-bundle, so it needs no
download. Fallback fonts are merged into the same ImGui font so CJK, Hangul,
symbols and emoji draw instead of "?" boxes (STEP2.md: the base fonts were
missing all 24 such characters in the test sample).

Known gaps (spike): the fallback paths are macOS system fonts (Linux would use
Noto); emoji draw monochrome; wide glyphs are not scaled to exactly 2 cells.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar

from imgui_bundle import imgui

__all__ = ["TerminalFont"]

logger = logging.getLogger(__name__)

SIZE = 14.0  # px before Lux's font_scale_main
_FREETYPE_LOAD_COLOR = 1 << 8  # ImGuiFreeTypeLoaderFlags_LoadColor (imgui_freetype.h)

_MONO = Path(
    str(__import__("imgui_bundle").__path__[0]),
    "assets",
    "fonts",
    "Inconsolata-Medium.ttf",
)
_FALLBACKS: tuple[tuple[str, bool], ...] = (  # (path, colour glyphs)
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", False),  # Chinese, kana
    ("/System/Library/Fonts/AppleSDGothicNeo.ttc", False),  # Hangul
    ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", False),  # symbols
    ("/System/Library/Fonts/Apple Color Emoji.ttc", True),  # emoji
)


class TerminalFont:
    """Loads the terminal font into the atlas once; the renderer pushes it."""

    font: ClassVar[imgui.ImFont | None] = None
    size: ClassVar[float] = SIZE

    @classmethod
    def load(cls) -> None:
        """Add the font to ImGui's atlas. Call from the font-loading callback."""
        if not _MONO.exists():
            logger.warning("terminal font not found at %s; using the UI font", _MONO)
            return
        atlas = imgui.get_io().fonts
        cls.font = atlas.add_font_from_file_ttf(str(_MONO), cls.size)
        merged = 0
        for path, color in _FALLBACKS:
            if not Path(path).exists():
                continue
            config = imgui.ImFontConfig()
            config.merge_mode = True
            if color:
                config.font_loader_flags = _FREETYPE_LOAD_COLOR
            atlas.add_font_from_file_ttf(path, cls.size, config)
            merged += 1
        logger.info("terminal font: %s + %d fallbacks", _MONO.name, merged)
