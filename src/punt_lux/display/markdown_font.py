"""Packaged DejaVu font for imgui_md — the arrow coverage its own font lacks.

imgui_md renders markdown with its own bundled text font (a Roboto subset) and no
symbol-merge hook, so glyphs outside that subset — the arrows among them — paint as
tofu. DejaVu Sans carries them in one file; this module points imgui_md at the
packaged four-weight DejaVu through a HelloImGui asset search path.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Final, Self

if TYPE_CHECKING:
    from collections.abc import Callable

    from imgui_bundle import imgui_md

__all__ = ["MarkdownFont"]

logger = logging.getLogger(__name__)

# imgui_md loads ``<base>-Regular.ttf`` and the -Bold / -BoldItalic / -RegularItalic
# siblings; the packaged DejaVu files carry exactly those names.
_WEIGHT_FILES: Final = (
    "DejaVu-Regular.ttf",
    "DejaVu-Bold.ttf",
    "DejaVu-BoldItalic.ttf",
    "DejaVu-RegularItalic.ttf",
)
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
        return tuple(stem / name for name in _WEIGHT_FILES)

    def _all_present(self) -> bool:
        """Return whether every packaged weight file is on disk."""
        return all(path.is_file() for path in self.weight_files())

    def apply_to(
        self, options: imgui_md.MarkdownOptions, register: Callable[[str], None]
    ) -> None:
        """Register the font dir via ``register`` and point ``options`` at its base.

        ``register`` is HelloImGui's ``add_assets_search_path``, injected so this
        module needs no imgui-bundle import; both it and the base-path set must precede
        ``InitializeMarkdown``, hence at ``AddOnsParams`` build time. A broken install
        missing any weight is left on imgui_md's default font (tofu arrows, warned)
        rather than pointed at absent files — that would fail the load deep in the
        immapp runner, uncatchable here, and kill the window.
        """
        if not self._all_present():
            logger.warning(
                "packaged markdown fonts missing; leaving imgui_md on its default "
                "font -- markdown arrows may render as tofu"
            )
            return
        register(str(self._dir))
        options.font_options.font_base_path = self.base_path
