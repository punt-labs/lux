"""ImGuiGroupRenderer — paint a GroupElement as an imgui-bundle stack layout.

The container counterpart to the leaf adapters: ``begin`` opens the stack
surface the group's ``layout`` selects (``begin_vertical`` for rows,
``begin_horizontal`` for columns), the render skeleton paints the children
through the default recursion, and ``end`` closes the matching surface.
``paint`` is a no-op — a container's only body is its children, exactly as
``ImGuiDialogRenderer.paint`` is a no-op.

Only the stack layouts render here; a ``paged`` group never reaches this
adapter (the wire decoder keeps paged groups on the legacy path), so an
unexpected layout fails loud rather than drawing nothing.
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
        layout = self._elem.layout
        if layout == "rows":
            imgui.begin_vertical(self._elem.id)
        elif layout == "columns":
            imgui.begin_horizontal(self._elem.id)
        else:
            msg = f"ImGuiGroupRenderer cannot render layout {layout!r}"
            raise ValueError(msg)
        return True

    def paint(self) -> None:
        """No-op — the group's only body is its children (default recursion)."""

    def end(self, *, opened: bool) -> None:
        """Close the stack surface ``begin`` opened for this group's layout."""
        if not opened:
            return
        layout = self._elem.layout
        if layout == "rows":
            imgui.end_vertical()
        elif layout == "columns":
            imgui.end_horizontal()
