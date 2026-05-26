"""Element ABC with template-method ``render()`` + ``_children()`` hook.

The ABC carries:

- ``render()`` — template method per Composite pattern; never overridden.
- ``_children()`` — hook composites override to return their children.
- ``renderer_factory`` + ``emit`` — injected at construction.
- ``apply_patch()`` — template for scene-graph in-place mutation; the
  default walks the patch dict calling ``_set_<key>`` per entry.
- A per-Element handler registry keyed by ``Event`` subclass, with
  ``add_handler`` / ``remove_handler`` / ``fire`` methods. The dispatch
  loop snapshots the handler list so a handler that mutates the registry
  cannot affect the in-flight call. The registry is the single dispatch
  site downstream of ``Display.interact``.
- A small property-observer surface — ``_removed``, ``_observers``,
  ``add_observer``, ``mark_removed`` — used by parent composites to
  react to a child element being removed (agent ``RemoveElement``,
  component self-dismiss, or connection disconnect all route through
  the one ``mark_removed`` method).

The PR-1 ``domain.element.Element`` Protocol is the **structural** contract
for wire dataclasses and continues to type the PR-2 element kinds. This
ABC is the **behavioral** contract for io-model element kinds. Both names
coexist; the file names keep them visually distinct.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Self, cast

from punt_lux.tracing import trace

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from punt_lux.domain.event_protocol import Event, Handler
    from punt_lux.protocol.messages.remote_invocation import (
        RemoteEventHandlerInvocation,
    )
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["Element"]

logger = logging.getLogger(__name__)


class Element(ABC):
    """Domain core for io-model element kinds.

    Subclasses add fields and (optionally) behavior methods. They do NOT
    override ``render()`` — Composite + the template handle it. Composites
    override ``_children()`` to return their children tuple; leaves
    inherit the empty default.
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

    def add_handler[E: Event](
        self,
        event_type: type[E],
        handler: Handler[E],
    ) -> None:
        """Register a handler for ``event_type`` on this Element."""
        bucket = self._handlers.setdefault(cast("type[Event]", event_type), [])
        bucket.append(cast("Handler[Event]", handler))

    def remove_handler[E: Event](
        self,
        event_type: type[E],
        handler: Handler[E],
    ) -> None:
        """Deregister a handler for ``event_type``. No-op if not present."""
        bucket = self._handlers.get(cast("type[Event]", event_type))
        if bucket is None:
            return
        try:
            bucket.remove(cast("Handler[Event]", handler))
        except ValueError:
            return
        if not bucket:
            del self._handlers[cast("type[Event]", event_type)]

    @trace
    def fire(self, event: Event) -> None:
        """Dispatch ``event`` to every handler registered for its type.

        Handlers are invoked in registration order against a snapshot of
        the list so a handler that mutates the registry mid-dispatch
        cannot affect the in-flight call. A handler that raises is
        logged with full traceback; remaining handlers still run — this
        is a fan-out boundary where one bad subscriber must not stop
        delivery to the others (PY-EH-6 system-boundary exemption).
        """
        snapshot = tuple(self._handlers.get(type(event), ()))
        for handler in snapshot:
            try:
                handler(event)
            except Exception:
                logger.exception(
                    "handler raised on %s for element %s",
                    type(event).__name__,
                    self.id,
                )

    def handler_count(self, event_type: type[Event]) -> int:
        """Return the number of handlers registered for ``event_type``."""
        bucket = self._handlers.get(event_type, ())
        return sum(self._logical_handler_count(handler) for handler in bucket)

    def handler_summary(self) -> dict[str, int]:
        """Return a name-to-count mapping of all registered handler types."""
        return {
            event_type.__name__: sum(
                self._logical_handler_count(handler) for handler in handlers
            )
            for event_type, handlers in self._handlers.items()
        }

    @trace
    def wrap_handlers_for_remote(
        self,
        send_fn: Callable[[RemoteEventHandlerInvocation], None],
    ) -> None:
        """Wrap each event bucket in one remote-dispatch group.

        Recurses into children via ``_children()``. Each handler on a
        ``ButtonElement`` or ``CheckboxElement`` stays part of the
        original semantic handler chain, but the Display-side transport
        wrapper batches each event bucket into one
        ``RemoteEventHandlerInvocation``. The Hub replays the full
        original handler chain once on its authoritative copy.
        """
        from punt_lux.domain.handlers.remote_dispatch import RemoteDispatchGroup
        from punt_lux.domain.interaction import ButtonClicked, ValueChanged
        from punt_lux.protocol.elements.button import ButtonElement
        from punt_lux.protocol.elements.checkbox import CheckboxElement

        if isinstance(self, ButtonElement):
            action = self.action or self.id
            button_handlers = self._handlers.get(ButtonClicked, ())
            if button_handlers and not (
                len(button_handlers) == 1
                and self._is_remote_dispatch_group(button_handlers[0])
            ):
                grouped = RemoteDispatchGroup(
                    handlers=tuple(button_handlers),
                    send=send_fn,
                    element_id=self.id,
                    action=action,
                    event_kind="button_clicked",
                )
                self._handlers[ButtonClicked] = [
                    cast("Handler[Event]", grouped),
                ]
        if isinstance(self, CheckboxElement):
            action = self.action
            value_handlers = self._handlers.get(ValueChanged, ())
            if value_handlers and not (
                len(value_handlers) == 1
                and self._is_remote_dispatch_group(value_handlers[0])
            ):
                grouped = RemoteDispatchGroup(
                    handlers=tuple(value_handlers),
                    send=send_fn,
                    element_id=self.id,
                    action=action,
                    event_kind="value_changed",
                )
                self._handlers[ValueChanged] = [
                    cast("Handler[Event]", grouped),
                ]
        for child in self._children():
            child.wrap_handlers_for_remote(send_fn)

    @staticmethod
    def _logical_handler_count(handler: object) -> int:
        """Return the logical handler count represented by ``handler``."""
        from punt_lux.domain.handlers.remote_dispatch import RemoteDispatchGroup

        if isinstance(handler, RemoteDispatchGroup):
            return handler.wrapped_count
        return 1

    @staticmethod
    def _is_remote_dispatch_group(handler: object) -> bool:
        """Return True when ``handler`` is the grouped remote wrapper."""
        from punt_lux.domain.handlers.remote_dispatch import RemoteDispatchGroup

        return isinstance(handler, RemoteDispatchGroup)

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
