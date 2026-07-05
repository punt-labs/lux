"""Element ABC with template-method ``render()`` + ``_children()`` hook.

The ABC carries:

- ``render()`` — template method per Composite pattern; never overridden.
  Not yet the production paint path (the Display paints via
  ``_paint_element``); a later PR revives it as the live path.
- ``_children()`` — hook composites override to return their children.
- ``renderer_factory`` + ``emit`` — set at construction. Off the display
  tier the factory is the fail-loud ``RaisingRendererFactory`` sentinel;
  the Display rebinds the real factory onto each received ABC element and
  its ABC ``_children`` (ABC nested in a legacy container is not reached).
- ``apply_patch()`` — template for scene-graph in-place mutation; the
  default walks the patch dict calling ``_set_<key>`` per entry.
- The event handler registry and remote-dispatch behavior come from the
  ``EventHandlerHost`` mixin (``add_handler`` / ``remove_handler`` /
  ``fire`` / ``wrap_handlers_for_remote``), kept in its own module so the
  render core and the dispatch concern each stay one responsibility.
- A small property-observer surface — ``_removed``, ``_observers``,
  ``add_observer``, ``mark_removed`` — used by parent composites to
  react to a child element being removed (agent ``RemoveElement``,
  component self-dismiss, or connection disconnect all route through
  the one ``mark_removed`` method).

The ``domain.element.Element`` Protocol is the **structural** contract
for wire dataclasses and continues to type the dataclass element kinds.
This ABC is the **behavioral** contract for the ABC element kinds. Both
names coexist; the file names keep them visually distinct.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Self

from punt_lux.domain.event_handler_host import EventHandlerHost

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from punt_lux.domain.event_protocol import Event, Handler
    from punt_lux.domain.validation import ValidationError
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["Element"]

logger = logging.getLogger(__name__)


class Element(EventHandlerHost, ABC):
    """Domain core for the ABC element kinds.

    Subclasses add fields and (optionally) behavior methods. They do NOT
    override ``render()`` — Composite + the template handle it. Composites
    override ``_children()`` to return their children tuple; leaves
    inherit the empty default. Event registration and dispatch come from
    the ``EventHandlerHost`` mixin.
    """

    _renderer_factory: RendererFactory
    _emit: Emit
    _handlers: dict[type[Event], list[Handler[Event]]]
    _removed: bool
    _observers: list[Callable[[str], None]]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
    ) -> Self:
        self = super().__new__(cls)
        self._renderer_factory = renderer_factory
        self._emit = emit
        self._handlers = {}
        self._removed = False
        self._observers = []
        return self

    def __reduce__(self) -> tuple[object, ...]:
        """Support native serialization for Hub-to-Display transport.

        Returns a (callable, args, state) triple so the deserializer
        can reconstruct via ``object.__new__`` (bypassing the ABC's
        keyword-only ``__new__``) then restore state via ``__setstate__``.

        Hub-side bookkeeping (``_observers``) contains closures that
        reference ``HubDisplay`` and cannot survive serialization. The
        Display is a replica — it does not need Hub observers. Handlers
        are preserved so ``wrap_handlers_for_remote`` can wrap them on
        the Display side.
        """
        state = {k: v for k, v in self.__dict__.items() if k != "_observers"}
        return (object.__new__, (type(self),), state)

    def __setstate__(self, state: dict[str, object]) -> None:
        """Restore instance state after native deserialization."""
        for key, value in state.items():
            object.__setattr__(self, key, value)
        object.__setattr__(self, "_observers", [])

    @property
    @abstractmethod
    def id(self) -> str:
        """Return the element's stable identity within its enclosing Scene."""

    def render(self) -> None:
        """Resolve a renderer and paint this subtree. NEVER overridden.

        Composite template method. Off the display tier
        ``_renderer_factory`` is the fail-loud sentinel, so a call raises
        unless the Display first rebinds the real factory via
        ``bind_renderer_factory``. Not yet the production paint path — the
        Display paints through ``_paint_element`` until a later PR flips it.
        """
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

    def bind_renderer_factory(self, factory: RendererFactory) -> None:
        """Rebind the renderer factory on this element and its subtree.

        Elements arrive off the wire carrying the sentinel factory (pickle
        preserves the constructing tier's). The Display calls this after
        receiving an element so ``render()`` resolves a real renderer.
        Recurses into ``_children()`` so a dialog and its buttons are
        rebound in one call.
        """
        self._renderer_factory = factory
        for child in self._children():
            child.bind_renderer_factory(factory)

    def validate(self) -> tuple[ValidationError, ...]:
        """Return this element's own validation errors.

        Sensible leaf default: no errors. Each kind overrides this to
        check what is *component-appropriate* for its widget — a table
        checks that rows fit its columns, a dialog would check its
        buttons are wired. The tree walk calls this on every element and
        accumulates the results; an element with nothing to check simply
        returns the empty default.
        """
        return ()

    def child_elements(self) -> tuple[Element, ...]:
        """Return direct children for the validation walk.

        Public bridge onto the protected ``_children()`` hook so the
        hierarchy-walking collector can recurse without reaching into
        renderer-facing internals. Composites get the right answer for
        free by virtue of overriding ``_children()``.
        """
        return self._children()

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
        in place (ABC elements are mutable; dataclass elements are frozen
        — the two branches converge in ``SceneManager._apply_patch_set``).
        """
        for key, value in patch.items():
            setter = getattr(self, f"_set_{key}", None)
            if setter is None:
                msg = f"{type(self).__name__} has no setter for patch field {key!r}"
                raise AttributeError(msg)
            setter(value)
        return self

    def add_observer(self, observer: Callable[[str], None]) -> None:
        """Register a property-change observer.

        Parent composites use this to react to children flipping
        ``_removed`` (and, in future, ``_visible`` / ``_enabled``).
        """
        self._observers.append(observer)

    @property
    def removed(self) -> bool:
        """Whether this Element has been marked removed from its scene."""
        return self._removed

    def mark_removed(self) -> None:
        """Flip ``_removed`` to True and notify observers. Idempotent.

        The single mechanism for marking any Element removed; all three
        removal paths (agent ``RemoveElement``, component self-dismiss,
        connection disconnect) reach it.

        Observers run against a snapshot of the list so a callback that
        mutates the registry mid-dispatch cannot affect the in-flight
        call. A callback that raises is logged with full traceback and
        the remaining observers still run — removal is a fan-out
        boundary where one bad subscriber must not strand the others
        (PY-EH-6 system-boundary exemption).
        """
        if self._removed:
            return
        self._removed = True
        for observer in tuple(self._observers):
            try:
                observer("removed")
            except Exception:
                logger.exception(
                    "observer raised on removed for element %s",
                    self.id,
                )
