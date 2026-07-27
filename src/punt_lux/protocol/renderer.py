"""Renderer + RendererFactory + Emit Protocols.

Render-side structural contracts. Wire-side codec contracts live next
door in ``codec_protocols.py`` (PY-OO-2: one concept per module).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from punt_lux.protocol.elements.tab import Tab

__all__ = [
    "ColumnsRenderer",
    "Emit",
    "Renderer",
    "RendererFactory",
    "TabContainerRenderer",
]


type Emit = Callable[[object], None]


@runtime_checkable
class Renderer(Protocol):
    """Per-kind ImGui surface driven by the Element render skeleton.

    ``begin`` opens the surface and returns whether the inner steps run;
    ``paint`` fills the node's own body; ``end`` closes it (``opened`` says
    whether ``begin`` opened anything). A leaf is a degenerate container:
    ``begin`` returns True, ``paint`` draws the widget, ``end`` is a no-op.
    """

    def begin(self) -> bool: ...
    def paint(self) -> None: ...
    def end(self, *, opened: bool) -> None: ...


@runtime_checkable
class TabContainerRenderer(Renderer, Protocol):
    """A ``Renderer`` that also brackets per-tab items for a tab bar.

    ``TabBarElement._render_children`` needs a broader surface than the shared
    leaf ``Renderer`` — one that opens a tab item, honours the Hub-authoritative
    active tab, and closes it — so the tab bar's adapter satisfies this
    sub-protocol rather than widening the shared ``Renderer`` (PY-IC-7).
    """

    def begin_tab(self, tab: Tab, *, active: str) -> bool: ...
    def end_tab(self, *, opened: bool) -> None: ...


@runtime_checkable
class ColumnsRenderer(Renderer, Protocol):
    """A ``Renderer`` that brackets each child of a ``columns`` group as a block.

    A columns group places its children left-to-right, but a child whose
    expansion paints several items (an open tree, an expanded header) must grow
    DOWN inside its own column rather than spread along the row. Each child
    renders inside its own block; the renderer advances to the next column
    between blocks. ``GroupElement._render_children`` drives the loop and this
    sub-protocol owns the ImGui, so the domain class stays ImGui-free (PY-IC-8),
    mirroring ``TabContainerRenderer`` for the tab bar.
    """

    def begin_child_block(self, *, first: bool) -> None: ...
    def end_child_block(self) -> None: ...


@runtime_checkable
class RendererFactory(Protocol):
    """Callable that resolves an Element to its per-kind renderer.

    One factory per Display, bound onto received elements by the Display's
    post-receive rebind (``Element.bind_renderer_factory``), not at decode.
    """

    def __call__(self, elem: object) -> Renderer: ...
