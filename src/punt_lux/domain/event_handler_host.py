"""EventHandlerHost — the per-Element event handler registry and dispatch mixin.

Split out of ``element_abc`` so the Element ABC's Composite-render core and
its event-dispatch concern each stay a single responsibility (PY-OO-2). The
mixin holds no instance data of its own (PY-IC-3, ``__slots__ = ()``); it
operates on the ``_handlers`` dict the composing ``Element`` creates in
``__new__`` and on the ``id`` / ``_children`` surface the Element provides.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, cast

from punt_lux.domain.ids import ElementId
from punt_lux.domain.interaction_errors import WrongKindError
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.element_abc import Element
    from punt_lux.domain.event_kinds import EventKind
    from punt_lux.domain.event_protocol import Event, Handler
    from punt_lux.domain.ids import ClientId, SceneId
    from punt_lux.domain.remote_dispatch_spec import RemoteDispatchSpec
    from punt_lux.domain.wire_event import WireEvent
    from punt_lux.protocol.messages.remote_invocation import (
        RemoteEventHandlerInvocation,
    )

__all__ = ["EventHandlerHost"]

logger = logging.getLogger(__name__)


class EventHandlerHost:
    """The per-Element handler registry keyed by ``Event`` subclass.

    Registers, deregisters, counts, and dispatches handlers, and wraps
    them for remote dispatch on the Display side. The registry is the
    single dispatch site downstream of ``Display.interact``; ``fire``
    snapshots the bucket so a handler that mutates the registry
    mid-dispatch cannot affect the in-flight call.
    """

    __slots__ = ()

    _handlers: dict[type[Event], list[Handler[Event]]]

    if TYPE_CHECKING:
        # Provided by the composing ``Element`` — declared for the type
        # checker so the mixin's ``self.id`` / ``self._children()`` resolve.
        @property
        def id(self) -> str: ...

        def _children(self) -> tuple[Element, ...]: ...

    def add_handler[E: Event](self, event_type: type[E], handler: Handler[E]) -> None:
        """Register a handler for ``event_type`` on this Element."""
        bucket = self._handlers.setdefault(cast("type[Event]", event_type), [])
        bucket.append(cast("Handler[Event]", handler))

    def remove_handler[E: Event](
        self, event_type: type[E], handler: Handler[E]
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
        """Wrap each interactive event bucket in one remote-dispatch group.

        Recurses into children via ``_children()``. Each element names the
        buckets to collapse through ``_remote_dispatch_specs`` — a button
        its ``ButtonClicked`` bucket, a checkbox its ``ValueChanged``
        bucket — so a new interactive kind is additive (PY-IC-7) instead of
        adding another branch here. Every handler stays part of the
        original semantic chain; the Display-side transport wrapper batches
        each bucket into one ``RemoteEventHandlerInvocation`` the Hub
        replays once on its authoritative copy.
        """
        for spec in self._remote_dispatch_specs():
            action = spec.action or self.id
            self._group_bucket_for_remote(
                spec.event_type, action, spec.event_kind, send_fn
            )
        for child in self._children():
            child.wrap_handlers_for_remote(send_fn)

    def build_remote_event(
        self,
        *,
        event_kind: str | None,
        scene_id: SceneId,
        owner_id: ClientId,
        value: object,
    ) -> WireEvent:
        """Build the typed event this element fires for a wire invocation.

        Polymorphic dispatch on the element in hand: match the invocation's
        ``event_kind`` against this element's own ``_remote_dispatch_specs`` and
        let the matched spec build the typed event (validating the payload's
        shape). No matching spec means the resolved element does not fire that
        kind — a ``kindless`` (``None``) invocation matches nothing either — so
        it is denied with ``WrongKindError`` at the boundary, never fired.
        """
        element_id = ElementId(self.id)
        for spec in self._remote_dispatch_specs():
            if spec.event_kind == event_kind:
                return spec.build_event(
                    scene_id=scene_id,
                    element_id=element_id,
                    owner_id=owner_id,
                    value=value,
                )
        raise WrongKindError(
            scene_id=scene_id,
            element_id=element_id,
            expected=self._interactive_kinds_summary(),
            got=repr(event_kind),
        )

    def _interactive_kinds_summary(self) -> str:
        """Return the wire kinds this element answers to, for a denial message."""
        kinds = [spec.event_kind for spec in self._remote_dispatch_specs()]
        return ", ".join(kinds) if kinds else "no interactive events"

    def _remote_dispatch_specs(self) -> tuple[RemoteDispatchSpec, ...]:
        """Return interactive-event specs to remote-wrap; empty by default."""
        return ()

    def _group_bucket_for_remote(
        self,
        event_type: type[Event],
        action: str,
        event_kind: EventKind,
        send_fn: Callable[[RemoteEventHandlerInvocation], None],
    ) -> None:
        """Replace one event bucket with a single remote-dispatch wrapper.

        No-op when the bucket is empty or already collapsed to one
        ``RemoteDispatchGroup`` (idempotent — a second wrap must not
        double-nest the group).
        """
        from punt_lux.domain.handlers.remote_dispatch import RemoteDispatchGroup

        handlers = self._handlers.get(event_type, ())
        if not handlers:
            return
        if len(handlers) == 1 and self._is_remote_dispatch_group(handlers[0]):
            return
        grouped = RemoteDispatchGroup(
            handlers=tuple(handlers),
            send=send_fn,
            element_id=self.id,
            action=action,
            event_kind=event_kind,
        )
        self._handlers[event_type] = [cast("Handler[Event]", grouped)]

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
