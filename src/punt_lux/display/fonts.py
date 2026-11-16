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

# SPIKE (terminal element): Inconsolata ships with imgui-bundle.
# The fallback font paths are macOS-only.
_MONO_FONT = Path(
    str(__import__("imgui_bundle").__path__[0]),
    "assets",
    "fonts",
    "Inconsolata-Medium.ttf",
)
_TERMINAL_FALLBACKS: tuple[tuple[str, bool], ...] = (
    ("/System/Library/Fonts/Hiragino Sans GB.ttc", False),
    ("/System/Library/Fonts/AppleSDGothicNeo.ttc", False),
    ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", False),
    ("/System/Library/Fonts/Apple Color Emoji.ttc", True),
)


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

        self._load_terminal_font()

    def _load_terminal_font(self) -> None:
        """SPIKE: monospace font for the terminal element, with CJK/emoji merged in."""
        from imgui_bundle import imgui

        from punt_lux.display.renderers.imgui.terminal import TerminalFonts

        mono = _MONO_FONT if _MONO_FONT.exists() else None
        if mono is None:
            logger.warning("terminal: monospace font not found at %s", _MONO_FONT)
            return
        io = imgui.get_io()
        size = TerminalFonts.size
        font = io.fonts.add_font_from_file_ttf(str(mono), size)
        for path, color in _TERMINAL_FALLBACKS:
            if not Path(path).exists():
                continue
            cfg = imgui.ImFontConfig()
            cfg.merge_mode = True
            if color:
                cfg.font_loader_flags = 1 << 8  # ImGuiFreeTypeLoaderFlags_LoadColor
            io.fonts.add_font_from_file_ttf(path, size, cfg)
        TerminalFonts.mono = font
        logger.info(
            "terminal: loaded %s + %d fallbacks", mono.name, len(_TERMINAL_FALLBACKS)
        )

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
