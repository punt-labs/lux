"""Renderer + RendererFactory + Emit Protocols.

Render-side structural contracts. Wire-side codec contracts live next
door in ``codec_protocols.py`` (PY-OO-2: one concept per module).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

__all__ = ["Emit", "Renderer", "RendererFactory"]


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
class RendererFactory(Protocol):
    """Callable that resolves an Element to its per-kind renderer.

    One factory per Display, bound onto received elements by the Display's
    post-receive rebind (``Element.bind_renderer_factory``), not at decode.
    """

    def __call__(self, elem: object) -> Renderer: ...
