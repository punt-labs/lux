# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for ProgressElement — emits an ImGui progress bar."""

from __future__ import annotations

from typing import Self

from imgui_bundle import ImVec2, imgui

from punt_lux.protocol.elements.progress import ProgressElement

__all__ = ["ProgressRenderer"]


class ProgressRenderer:
    """Render a ProgressElement via imgui.progress_bar."""

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def render(self, elem: ProgressElement) -> None:
        overlay = elem.label if elem.label else f"{int(elem.fraction * 100)}%"
        imgui.progress_bar(elem.fraction, ImVec2(-1, 0), overlay)
