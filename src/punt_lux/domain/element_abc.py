"""Element ABC with template-method ``render()`` + ``_children()`` hook.

Per docs/oo-refactor/pr3-v2.1-design.md §1 row 1 and the spike at
``spikes/io_model_v1/src/lux_spike/element.py``:

- ``render()`` is the template method on the ABC, **never** overridden.
- ``_children()`` is the hook composites override to return their children.
- ``renderer_factory`` + ``emit`` are injected at construction (DI per DES-032).
- ``apply_patch()`` is the template for scene-graph in-place mutation;
  the default implementation walks the patch dict calling ``_set_<key>``
  per entry. Used by ``SceneManager._apply_patch_set`` for ABC elements
  (D6 from the amended design).

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
    from collections.abc import Mapping

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

    def apply_patch(self, patch: Mapping[str, object]) -> Self:
        """Apply a field patch in place by dispatching to ``_set_<key>``.

        Default implementation: for each ``(key, value)`` pair, look up
        ``_set_{key}`` on ``self`` and call it with the value. Subclasses
        override this only when patch semantics differ from one setter
        per field; the common case is the default.

        Public method (not ``_patch``) because ``SceneManager._apply_patch_set``
        invokes it from outside the class — a leading underscore would
        trigger pyright's ``reportPrivateUsage`` even though the call is
        the documented contract. Internal ``_set_<key>`` helpers stay
        private to this class.

        Returns ``self`` so the call site can be a drop-in replacement
        for the dataclass ``replace(...)`` path. The element is mutated
        in place (io-model elements are mutable; dataclass elements are
        frozen — the two branches converge in ``SceneManager._apply_patch_set``).
        """
        for key, value in patch.items():
            setter = getattr(self, f"_set_{key}", None)
            if setter is None:
                msg = f"{type(self).__name__} has no setter for patch field {key!r}"
                raise AttributeError(msg)
            setter(value)
        return self
