"""Element ABC with template-method render() + _children() hook.

Per io-model.md §"The Element — domain core" and DES-032:
- render() is the template method on the ABC, never overridden.
- _children() is the hook composites override.
- renderer_factory + emit are injected at construction (DI per DES-032).
"""

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from lux_spike.protocols import Emit, RendererFactory


class Element(ABC):
    """Domain core. Subclasses add fields + (optionally) behavior methods.
    They do NOT override render() — composition + the template handle it."""

    _renderer_factory: RendererFactory
    _emit: Emit

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
    ) -> Self:
        self = super().__new__(cls)
        self._renderer_factory = renderer_factory
        self._emit = emit
        return self

    def render(self) -> None:
        """Template method per Composite pattern. NEVER overridden."""
        renderer = self._renderer_factory(self)
        children = self._children()
        if children:
            renderer.begin()
            try:
                for child in children:
                    child.render()
            finally:
                renderer.end()
        else:
            renderer.render()

    def _children(self) -> tuple[Element, ...]:
        """Hook — composites override to return their children. Leaves
        inherit the empty default."""
        return ()
