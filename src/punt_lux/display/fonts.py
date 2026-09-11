"""FontLoader -- the Display's Unicode font discovery and hello_imgui loading.

Extracted from ``RenderLoop`` (PY-IC-6): finding a system text font with broad
Unicode coverage and merging symbol fonts on top (math angle brackets, Z
notation double-struck letters) is one self-contained concern, touching none of
the render loop's socket, scene, or replica state. :meth:`load` is the
``hello_imgui`` ``load_additional_fonts`` callback the render loop registers.
"""

from __future__ import annotations

import logging
import platform
from pathlib import Path
from typing import Self, final

logger = logging.getLogger(__name__)

__all__ = ["FontLoader"]

_FONT_SIZE = 16.0


@final
class FontLoader:
    """Discovers system Unicode fonts and loads them into ``hello_imgui``."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def load(self) -> None:
        """Load a Unicode text font plus merged symbol fonts (the callback).

        Replaces ImGui's Latin-only built-in default; a second symbol font is
        merged on top to fill remaining gaps. A no-op-with-error-log when no
        Unicode font is found rather than a crash -- the window still renders,
        just without symbol coverage.
        """
        from imgui_bundle import hello_imgui

        primary, merge_fonts = self._find()
        if primary is None:
            logger.error(
                "No Unicode font found -- using ImGui default (Latin-only). "
                "Unicode symbols will not render correctly."
            )
            return

        params = hello_imgui.FontLoadingParams()
        params.inside_assets = False
        hello_imgui.load_font(primary, _FONT_SIZE, params)
        logger.info("Loaded primary font: %s", primary)

        for sym_path in merge_fonts:
            merge_params = hello_imgui.FontLoadingParams()
            merge_params.inside_assets = False
            merge_params.merge_to_last_font = True
            hello_imgui.load_font(sym_path, _FONT_SIZE, merge_params)
            logger.info("Merged symbol font: %s", sym_path)

    def _find(self) -> tuple[str | None, list[str]]:
        """Return ``(primary, merge_fonts)`` for the current platform."""
        if platform.system() == "Darwin":
            primary = self._first_existing(
                "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
                "/System/Library/Fonts/Helvetica.ttc",
            )
            # Apple Symbols fills gaps (math angle brackets U+27E8/E9, etc.)
            sym = self._first_existing("/System/Library/Fonts/Apple Symbols.ttf")
            # STIX Two Math covers Mathematical Alphanumeric Symbols
            # (U+1D400-1D7FF) -- needed for Z notation double-struck letters
            math = self._first_existing(
                "/System/Library/Fonts/Supplemental/STIXTwoMath.otf",
                "/Library/Fonts/STIXTwoMath.otf",
            )
        else:
            # Linux -- DejaVu has good symbol coverage; Noto as fallback
            primary = self._first_existing(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/TTF/DejaVuSans.ttf",
                "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
                "/usr/share/fonts/noto/NotoSans-Regular.ttf",
            )
            # Noto Sans Symbols for anything DejaVu misses
            sym = self._first_existing(
                "/usr/share/fonts/truetype/noto/NotoSansSymbols2-Regular.ttf",
                "/usr/share/fonts/noto/NotoSansSymbols2-Regular.ttf",
            )
            # Noto Sans Math covers Mathematical Alphanumeric Symbols
            # (U+1D400-1D7FF) -- needed for Z notation double-struck letters
            math = self._first_existing(
                "/usr/share/fonts/truetype/noto/NotoSansMath-Regular.ttf",
                "/usr/share/fonts/noto/NotoSansMath-Regular.ttf",
            )
        return primary, [font for font in (sym, math) if font is not None]

    @staticmethod
    def _first_existing(*candidates: str) -> str | None:
        """Return the first candidate path that is an existing file, or ``None``."""
        for p in candidates:
            if Path(p).is_file():
                return p
        return None
