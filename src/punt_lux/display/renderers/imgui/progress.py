# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""ImGuiProgressRenderer — Renderer-Protocol adapter for ``ProgressElement``.

A display-only leaf that draws a single ``imgui.progress_bar`` directly — a
progress bar has no style/color sub-renderer to reuse, so drawing here keeps the
ABC path self-contained (fork, don't mix). The overlay falls back to the
percentage when no label is set, preserving the legacy renderer's pixels.
``LeafRenderer`` adds the shared tooltip pass and the geometry capture around it.
"""

from __future__ import annotations

from typing import final

from imgui_bundle import ImVec2, imgui

from punt_lux.display.renderers.imgui.leaf import LeafRenderer
from punt_lux.protocol.elements.progress import ProgressElement

__all__ = ["ImGuiProgressRenderer"]


@final
class ImGuiProgressRenderer(LeafRenderer[ProgressElement]):
    """Paint a ProgressElement via imgui.progress_bar + the shared tooltip pass."""

    __slots__ = ()

    def _paint_widget(self) -> None:
        """Draw the progress bar (percentage overlay fallback)."""
        elem = self._elem
        overlay = elem.label or f"{int(elem.fraction * 100)}%"
        imgui.progress_bar(elem.fraction, ImVec2(-1, 0), overlay)
