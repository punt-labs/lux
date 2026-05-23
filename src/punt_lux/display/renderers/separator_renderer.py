# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""Renderer for SeparatorElement — emits an ImGui separator line."""

from __future__ import annotations

from typing import Self

from imgui_bundle import imgui

from punt_lux.protocol.elements.separator import SeparatorElement

__all__ = ["SeparatorRenderer"]


class SeparatorRenderer:
    """Render a SeparatorElement via imgui.separator()."""

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def render(self, _elem: SeparatorElement) -> None:
        imgui.separator()
