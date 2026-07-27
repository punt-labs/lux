"""ImGuiGroupRenderer — paint a GroupElement as a rows or columns layout.

The container counterpart to the leaf adapters. Rows use imgui-bundle's vertical
stack (``begin_vertical``); the render skeleton paints the children through the
default recursion. Columns use classic flow instead: ``begin`` opens one bounding
``begin_group`` and ``GroupElement._render_children`` brackets each child in its
own ``begin_group`` with ``same_line`` between, so a child whose expansion paints
several items grows DOWN inside its column rather than spreading the row — the
failure the horizontal stack layout produced. ``paint`` is a no-op — a container's
only body is its children, exactly as ``ImGuiDialogRenderer.paint`` is a no-op.

This adapter satisfies ``ColumnsRenderer`` (the per-child block surface) so the
domain ``GroupElement`` stays ImGui-free, mirroring the tab bar's
``TabContainerRenderer``. A ``GroupElement``'s ``layout`` is
``Literal["rows", "columns"]``, so those two are the only cases it sees.
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
        """Open the surface for this group's layout; always visible.

        Rows open a vertical stack. Columns open one plain ``begin_group`` that
        bounds the whole row so the hover tooltip covers every column; the
        per-column blocks and their horizontal placement are driven by
        ``GroupElement._render_children`` through this adapter's block surface.
        """
        if self._elem.layout == "rows":
            imgui.begin_vertical(self._elem.id)
        else:
            imgui.begin_group()
        return True

    def paint(self) -> None:
        """No-op — the group's only body is its children (default recursion)."""

    def end(self, *, opened: bool) -> None:
        """Close the surface ``begin`` opened, then apply the hover tooltip."""
        if opened:
            if self._elem.layout == "rows":
                imgui.end_vertical()
            else:
                imgui.end_group()
        self._factory.apply_tooltip(self._elem)

    def begin_child_block(self, *, first: bool) -> None:
        """Open a vertical block for one columns child, placed beside the previous.

        Classic ImGui flow inside the block stacks the child's items DOWN; the
        ``same_line`` before every block after the first lays the columns out
        left-to-right.
        """
        if not first:
            imgui.same_line()
        imgui.begin_group()

    def end_child_block(self) -> None:
        """Close the current columns child's block."""
        imgui.end_group()
