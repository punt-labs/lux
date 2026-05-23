"""Element ABC with template-method ``render()`` + ``_children()`` hook.

Per docs/oo-refactor/pr3-v2.1-design.md §1 row 1 and the spike at
``spikes/io_model_v1/src/lux_spike/element.py``:

- ``render()`` is the template method on the ABC, **never** overridden.
- ``_children()`` is the hook composites override to return their children.
- ``renderer_factory`` + ``emit`` are injected at construction (DI per DES-032).

The PR-1 ``domain.element.Element`` Protocol is the **structural** contract
for wire dataclasses and continues to type the 23 PR-2 element kinds. This
ABC is the **behavioral** contract for io-model element kinds — Text in
PR 3, Button/Panel/Dialog in PR 4. Both names coexist; the file names
keep them visually distinct.
"""

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["Element"]


class Element(ABC):
    """Domain core for io-model element kinds.

    Subclasses add fields and (optionally) behavior methods. They do NOT
    override ``render()`` — Composite + the template handle it. Composites
    override ``_children()`` to return their children tuple; leaves
    inherit the empty default.
    """

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
