"""Packaged DejaVu font for imgui_md — the arrow coverage its own font lacks.

imgui_md renders markdown through its own bundled text font (a Roboto subset) and
exposes no symbol-merge hook, so any glyph outside that subset — U+2192 and the
other arrows among them — paints as tofu, even though Lux's primary font renders
them fine via its symbol-font merge. DejaVu Sans carries the arrows in a single
file; this module points imgui_md at the packaged four-weight DejaVu through a
HelloImGui asset search path, so the markdown font resolves to it at startup.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Final, Self

if TYPE_CHECKING:
    from collections.abc import Callable

    from imgui_bundle import imgui_md

__all__ = ["MarkdownFont"]

# imgui_md loads ``<base>-Regular.ttf`` and the -Bold / -BoldItalic / -RegularItalic
# siblings; the packaged DejaVu files carry exactly those suffixes.
_WEIGHT_SUFFIXES: Final = ("Regular", "Bold", "BoldItalic", "RegularItalic")
# ``font_base_path`` is resolved relative to the registered search dir.
_BASE_PATH: Final = "dejavu/DejaVu"


class MarkdownFont:
    """The packaged DejaVu markdown font: its files and its imgui_md wiring."""

    _dir: Path
    __slots__ = ("_dir",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._dir = Path(__file__).parent / "fonts"
        return self

    @property
    def search_dir(self) -> Path:
        """The directory added to HelloImGui's asset search paths."""
        return self._dir

    @property
    def base_path(self) -> str:
        """imgui_md's ``font_base_path``, relative to :attr:`search_dir`."""
        return _BASE_PATH

    def weight_files(self) -> tuple[Path, ...]:
        """Return the four weight files imgui_md resolves under the base path."""
        stem = self._dir / "dejavu"
        return tuple(stem / f"DejaVu-{suffix}.ttf" for suffix in _WEIGHT_SUFFIXES)

    def apply_to(
        self, options: imgui_md.MarkdownOptions, register: Callable[[str], None]
    ) -> None:
        """Register the font dir via ``register`` and point ``options`` at its base.

        ``register`` is HelloImGui's ``add_assets_search_path``, injected so this
        module needs no imgui-bundle import. Adding the packaged font directory as a
        search path makes the relative ``base_path`` resolve to it; both must happen
        before ``InitializeMarkdown`` loads the markdown fonts, hence at
        ``AddOnsParams`` build time.
        """
        register(str(self._dir))
        options.font_options.font_base_path = self.base_path
