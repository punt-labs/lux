# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""ImGuiProgressRenderer — Renderer-Protocol adapter for ``ProgressElement``.

A display-only leaf: ``begin`` proceeds (nothing to open), ``paint`` draws a
single ``imgui.progress_bar`` directly — a progress bar has no style/color
sub-renderer to reuse, so drawing here keeps the ABC path self-contained
(fork, don't mix) — and ``end`` is a no-op. The overlay falls back to the
percentage when no label is set, preserving the legacy renderer's pixels.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from imgui_bundle import ImVec2, imgui

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol.elements.progress import ProgressElement

__all__ = ["ImGuiProgressRenderer"]


@final
class ImGuiProgressRenderer:
    """Paint a ProgressElement via imgui.progress_bar + the shared tooltip pass."""

    _elem: ProgressElement
    _factory: ImGuiRendererFactory

    def __new__(cls, elem: ProgressElement, factory: ImGuiRendererFactory) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        self._factory = factory
        return self

    def begin(self) -> bool:
        """Leaf — no surface to open; proceed to paint."""
        return True

    def paint(self) -> None:
        """Draw the progress bar (percentage overlay fallback) + tooltip pass."""
        elem = self._elem
        overlay = elem.label or f"{int(elem.fraction * 100)}%"
        imgui.progress_bar(elem.fraction, ImVec2(-1, 0), overlay)
        self._factory.apply_tooltip(elem)

    def end(self, *, opened: bool) -> None:
        """Leaf — no surface to close."""
        _ = opened
