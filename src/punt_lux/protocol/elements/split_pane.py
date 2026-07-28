"""SplitPaneElement — two vertically-stacked panes with a draggable divider.

The composed table's grid and detail share the frame through a draggable
horizontal divider that reallocates their heights. That two-pane vertical split
lives here as its own container rather than a special case of the ``rows`` group.

A ``SplitPaneElement`` is a ``GroupElement`` refinement: a rows stack of exactly
two children, ``top`` above the divider and ``bottom`` below it, rendered by a
``SplitPaneRenderer`` that owns the ImGui splitter. The split ratio is
Display-local view state (like a column width or the Display-side sort), so it
never crosses to the Hub; ``default_ratio`` is only the *initial* top-height
fraction, superseded the moment the user drags. On the Hub→Display wire the pane
crosses as its exact type (native pickle), so the Display resolves the split
renderer; the JSON codec it inherits still emits ``kind="group"``.

One trade-off of that inherited codec: through ``inspect_scene`` the live split
is indistinguishable from a plain rows group (same ``kind`` and
``resolved_props``), because the divider and its ratio are Display-local, not Hub
state — confirmed visually and by the renderer tests, not introspection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self, runtime_checkable

from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.group import GroupElement
from punt_lux.protocol.renderer import Renderer

if TYPE_CHECKING:
    from punt_lux.domain.element_abc import Element
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["SplitPaneElement", "SplitPaneRenderer"]

_DEFAULT_TOP_RATIO = 0.6  # initial top-height fraction when a caller sets none


@runtime_checkable
class SplitPaneRenderer(Renderer, Protocol):
    """The render surface a ``SplitPaneElement`` requires of its adapter.

    ``_render_children`` renders the top child, draws the divider, then the
    bottom child; this sub-protocol owns the ImGui (the two pane regions and the
    ``splitter_behavior`` grab), keeping the element ImGui-free (PY-IC-8).
    ``open_top`` reads the stored ratio; ``draw_divider`` writes it back on a drag.
    """

    def open_top(self) -> None: ...
    def close_top(self) -> None: ...
    def draw_divider(self) -> None: ...
    def open_bottom(self) -> None: ...
    def close_bottom(self) -> None: ...


class SplitPaneElement(GroupElement):
    """A rows split of a top and a bottom pane with a draggable divider."""

    _default_ratio: float

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory = RAISING_FACTORY,
        emit: Emit = NO_EMIT,
        id: str,
        top: Element,
        bottom: Element,
        default_ratio: float = _DEFAULT_TOP_RATIO,
    ) -> Self:
        self = super().__new__(
            cls,
            renderer_factory=renderer_factory,
            emit=emit,
            id=id,
            layout="rows",
            children=(top, bottom),
        )
        self._default_ratio = default_ratio
        return self

    @property
    def default_ratio(self) -> float:
        """Return the initial top-height fraction, before any user drag."""
        return self._default_ratio

    def _render_children(self, renderer: Renderer) -> None:
        """Render the top pane, draw the divider, then render the bottom pane.

        The domain drives the order; the ``SplitPaneRenderer`` owns the two
        ``begin_child`` pane regions and the splitter grab between them (PY-IC-8),
        exactly as a columns group hands its block brackets to a
        ``ColumnsRenderer``. A plain ``Renderer`` lacking the split surface is
        rejected here at the boundary, not deep in an opaque ``AttributeError``.
        """
        if not isinstance(renderer, SplitPaneRenderer):
            msg = (
                f"split pane {self.id!r} requires a SplitPaneRenderer "
                f"(open_top/draw_divider/open_bottom), got {type(renderer).__name__}"
            )
            raise TypeError(msg)
        top, bottom = self._children_tuple
        renderer.open_top()
        try:
            top.render()
        finally:
            renderer.close_top()
        renderer.draw_divider()
        renderer.open_bottom()
        try:
            bottom.render()
        finally:
            renderer.close_bottom()
