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
    """Per-kind renderer for one surface.

    Leaves implement ``render()``; composites implement ``begin()`` and
    ``end()`` to bracket their children. The Element ABC's template method
    chooses which path to take based on whether ``_children()`` is empty.
    """

    def render(self) -> None: ...
    def begin(self) -> None: ...
    def end(self) -> None: ...


@runtime_checkable
class RendererFactory(Protocol):
    """Callable that resolves an Element to its per-kind renderer.

    One factory per Display, constructed once at startup and threaded
    through the element tree at decode time.
    """

    def __call__(self, elem: object) -> Renderer: ...
