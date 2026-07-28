"""SplitPaneElement — two vertically-stacked panes with a draggable divider.

The composed table's grid and detail share the frame through a draggable
horizontal divider that reallocates their heights — a two-pane vertical split,
its own container rather than a special case of the ``rows`` group.

A ``SplitPaneElement`` is a ``GroupElement`` refinement: a rows stack of exactly
two children, ``top`` above the divider and ``bottom`` below it, rendered by a
``SplitPaneRenderer``. The split ratio is Display-local view state (like a column
width) superseded on the first drag, so it never crosses to the Hub. On the
Hub→Display wire the pane crosses as its exact type (native pickle), so the
Display resolves the split renderer; its inherited JSON codec emits ``kind="group"``.

A trade-off of that codec: ``inspect_scene`` shows the live split as a plain rows
group (same ``kind`` / ``resolved_props``); the divider and ratio are
Display-local, confirmed by the renderer tests and the eye, not introspection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self, runtime_checkable

from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.group import GroupElement
from punt_lux.protocol.renderer import Renderer

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.element_abc import Element
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["SplitPaneElement", "SplitPaneRenderer"]

_DEFAULT_TOP_RATIO = 0.6  # initial top-height fraction when a caller sets none


@runtime_checkable
class SplitPaneRenderer(Renderer, Protocol):
    """The render surface a ``SplitPaneElement`` requires of its adapter.

    Owns the ImGui — the two pane regions and the ``splitter_behavior`` grab —
    keeping the element ImGui-free (PY-IC-8): ``open_top`` reads the stored ratio,
    ``draw_divider`` writes it back on a drag.
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

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        """Reject wire decode — a split pane is server-constructed, never decoded.

        The pane emits ``kind="group"`` and its JSON decodes as a plain rows
        ``GroupElement`` through the registry — the documented one-way degradation
        (see the module docstring). The inherited ``GroupElement.from_dict`` would
        call ``cls(id=, layout=, children=, tooltip=)``, keywords this ``__new__``
        does not accept, raising a confusing ``TypeError``; refuse explicitly.
        """
        _ = d
        msg = (
            "SplitPaneElement is server-constructed and has no wire decode: its "
            "JSON emits kind='group' and decodes as a plain rows GroupElement "
            "through the element registry"
        )
        raise ValueError(msg)

    def _render_children(self, renderer: Renderer) -> None:
        """Render the top pane, draw the divider, then render the bottom pane.

        The domain drives the order; the ``SplitPaneRenderer`` owns the two pane
        regions and the splitter grab (PY-IC-8). A detach can leave other than two
        children — a patch removing the detail drops it to one — with nothing to
        split, so the remaining child (or none) renders as the inherited plain rows
        stack rather than raising a two-value unpack that would kill the frame; the
        ``SplitPaneRenderer`` is required only for a real split.
        """
        if len(self._children_tuple) != 2:
            super()._render_children(renderer)
            return
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
