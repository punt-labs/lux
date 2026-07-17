# pyright: reportUnknownMemberType=false, reportMissingModuleSource=false
"""TooltipPainter — the shared generic hover-tooltip pass.

The post-processing every per-kind adapter and the legacy dispatch share:
paint an element's hover tooltip when it has one. Unstyled text with a
tooltip is skipped — its ``TextRenderer`` paints it with ``selectable()``
and emits the tooltip inline, so a second pass here would double it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from imgui_bundle import imgui

if TYPE_CHECKING:
    from punt_lux.protocol import Element

__all__ = ["TooltipPainter"]


@final
class TooltipPainter:
    """Paint an element's generic hover tooltip, honouring the text guard."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def paint(self, elem: Element) -> None:
        """Paint ``elem``'s hover tooltip, if it has one and is not inline text."""
        if self._is_text_with_inline_tooltip(elem):
            return
        tooltip = getattr(elem, "tooltip", None)
        if tooltip and imgui.is_item_hovered(imgui.HoveredFlags_.for_tooltip.value):
            imgui.set_tooltip(tooltip)

    @staticmethod
    def _is_text_with_inline_tooltip(elem: Element) -> bool:
        """Return whether ``elem`` is unstyled text that paints its own tooltip.

        ``TextRenderer`` draws unstyled-with-tooltip text through
        ``selectable()`` and emits the tooltip inline, so the generic pass
        must skip it or the tooltip shows twice.
        """
        return bool(
            elem.kind == "text"
            and not getattr(elem, "style", None)
            and getattr(elem, "tooltip", None)
        )
