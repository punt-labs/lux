"""Discover Unicode fonts and load the Display's shared and terminal atlases."""

from __future__ import annotations

import logging
import platform
from pathlib import Path
from typing import ClassVar, Self, final

logger = logging.getLogger(__name__)
__all__ = ["FontLoader"]
_FONT_SIZE = 16.0


@final
class FontLoader:
    """Atlas loading backed by platform-specific candidate groups."""

    __slots__ = ()
    # Primary, symbols, mathematical alphanumerics: first available in each.
    _CANDIDATES: ClassVar[dict[str, tuple[tuple[str, ...], ...]]] = {
        "Darwin": (
            (
                "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
                "/System/Library/Fonts/Helvetica.ttc",
            ),
            ("/System/Library/Fonts/Apple Symbols.ttf",),
            (
                "/System/Library/Fonts/Supplemental/STIXTwoMath.otf",
                "/Library/Fonts/STIXTwoMath.otf",
            ),
        ),
        "Linux": (
            (
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/TTF/DejaVuSans.ttf",
                "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
                "/usr/share/fonts/noto/NotoSans-Regular.ttf",
            ),
            (
                "/usr/share/fonts/truetype/noto/NotoSansSymbols2-Regular.ttf",
                "/usr/share/fonts/noto/NotoSansSymbols2-Regular.ttf",
            ),
            (
                "/usr/share/fonts/truetype/noto/NotoSansMath-Regular.ttf",
                "/usr/share/fonts/noto/NotoSansMath-Regular.ttf",
            ),
        ),
    }

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def load(self) -> None:
        """Load primary text, symbol fallbacks, then the terminal font."""
        from imgui_bundle import hello_imgui

        primary, merge_fonts = self._find()
        if primary is None:
            logger.error("No Unicode font found -- using ImGui default (Latin-only)")
            return
        for index, path in enumerate([primary, *merge_fonts]):
            params = hello_imgui.FontLoadingParams()
            params.inside_assets = False
            params.merge_to_last_font = index > 0
            hello_imgui.load_font(path, _FONT_SIZE, params)
            logger.info(
                "Loaded %s font: %s", "primary" if index == 0 else "symbol", path
            )
        self._load_terminal_font()

    @staticmethod
    def _load_terminal_font() -> None:
        from punt_lux.display.terminal.font import TerminalFont

        TerminalFont.load()

    def _find(self) -> tuple[str | None, list[str]]:
        """Choose the first existing font from each platform candidate group."""
        candidates = self._CANDIDATES.get(platform.system(), self._CANDIDATES["Linux"])
        primary = self._first_existing(*candidates[0])
        extras = [self._first_existing(*group) for group in candidates[1:]]
        return primary, [path for path in extras if path is not None]

    @staticmethod
    def _first_existing(*candidates: str) -> str | None:
        for path in candidates:
            if Path(path).is_file():
                return path
        return None
