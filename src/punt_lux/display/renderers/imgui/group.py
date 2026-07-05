"""ImGuiGroupRenderer — paint a GroupElement as an imgui-bundle stack layout.

The container counterpart to the leaf adapters: ``begin`` opens the stack
surface the group's ``layout`` selects (``begin_vertical`` for rows,
``begin_horizontal`` for columns), the render skeleton paints the children
through the default recursion, and ``end`` closes the matching surface.
``paint`` is a no-op — a container's only body is its children, exactly as
``ImGuiDialogRenderer.paint`` is a no-op.

An ABC ``GroupElement``'s ``layout`` is ``Literal["rows", "columns"]`` —
``paged`` lives entirely on the legacy path — so ``rows`` and its
complement are the only two cases this adapter ever sees.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from imgui_bundle import imgui

if TYPE_CHECKING:
    from punt_lux.display.renderers.imgui.factory import ImGuiRendererFactory
    from punt_lux.protocol.elements.group import GroupElement

__all__ = ["ImGuiGroupRenderer"]


@final
class ImGuiGroupRenderer:
    """Paint a ``GroupElement`` as a vertical/horizontal stack (begin/paint/end)."""

    _elem: GroupElement
    _factory: ImGuiRendererFactory

    def __new__(cls, elem: GroupElement, factory: ImGuiRendererFactory) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        self._factory = factory
        return self

    def begin(self) -> bool:
        """Open the stack surface for this group's layout; always visible."""
        if self._elem.layout == "rows":
            imgui.begin_vertical(self._elem.id)
        else:
            imgui.begin_horizontal(self._elem.id)
        return True

    def paint(self) -> None:
        """No-op — the group's only body is its children (default recursion)."""

    def end(self, *, opened: bool) -> None:
        """Close the stack surface ``begin`` opened for this group's layout."""
        if not opened:
            return
        if self._elem.layout == "rows":
            imgui.end_vertical()
        else:
            imgui.end_horizontal()
