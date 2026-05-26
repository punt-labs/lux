"""Remote-dispatch wrappers for two-tier handler systems.

When the Hub and Display are separate processes, the display-side
element factory wraps every interaction handler in ``remote_dispatch``
so that ``element.fire(event)`` on the Display side sends a
``RemoteEventHandlerInvocation`` to the Hub instead of executing the
handler body. On the Hub side, the same handlers are decoded without
wrapping and execute directly.

Two event types (``ButtonClicked``, ``ValueChanged``) on both tiers.
The wrapping is the distribution concern — handler code,
``element.fire()``, and the catalog factories are identical on both
sides.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Self

from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.event_protocol import Event, Handler
    from punt_lux.domain.interaction import EventKind

__all__ = ["RemoteDispatchGroup", "remote_dispatch"]

_log = logging.getLogger(__name__)

type SendFn = Callable[[RemoteEventHandlerInvocation], None]


class RemoteDispatchGroup:
    """Wrap one element-event handler bucket into one remote send.

    The Display keeps the original handlers grouped inside this object
    so the semantic unit remains "the element's event handler chain",
    not "one transport wrapper per inner handler". One interaction on
    the Display yields one ``RemoteEventHandlerInvocation``; the Hub
    then resolves the authoritative element and runs the full original
    handler chain once on its copy.
    """

    __slots__ = (
        "_action",
        "_element_id",
        "_event_kind",
        "_original_handlers",
        "_send",
    )

    _original_handlers: tuple[Handler[Event], ...]
    _send: SendFn
    _element_id: str
    _action: str
    _event_kind: EventKind

    def __new__(
        cls,
        *,
        handlers: tuple[Handler[Event], ...],
        send: SendFn,
        element_id: str,
        action: str,
        event_kind: EventKind = "button_clicked",
    ) -> Self:
        if not handlers:
            msg = "RemoteDispatchGroup requires at least one handler"
            raise ValueError(msg)
        self = super().__new__(cls)
        self._original_handlers = handlers
        self._send = send
        self._element_id = element_id
        self._action = action
        self._event_kind = event_kind
        return self

    @property
    def wrapped_count(self) -> int:
        """Return the logical number of original handlers in this group."""
        return len(self._original_handlers)

    @property
    def original_handlers(self) -> tuple[Handler[Event], ...]:
        """Return the original handlers this group wraps."""
        return self._original_handlers

    @trace
    def __call__(self, event: Event) -> None:
        # Lazy import avoids circular dependency; interaction.py
        # imports nothing from this module so the cycle is clean.
        from punt_lux.domain.interaction import (  # noqa: PLC0415
            ButtonClicked,
            ValueChanged,
        )

        if isinstance(event, ValueChanged):
            value: object = event.value
        elif isinstance(event, ButtonClicked):
            value = True
        else:
            _log.warning(
                "RemoteDispatchGroup unrecognized event type %s for element_id=%s",
                type(event).__name__,
                self._element_id,
            )
            return

        _log.debug(
            "remote_dispatch sending element_id=%s action=%s "
            "event_kind=%s grouped_handlers=%d",
            self._element_id,
            self._action,
            self._event_kind,
            self.wrapped_count,
        )
        self._send(
            RemoteEventHandlerInvocation(
                element_id=self._element_id,
                action=self._action,
                event_kind=self._event_kind,
                ts=time.time(),
                value=value,
            )
        )


def remote_dispatch(
    inner: Handler[Event],
    send: SendFn,
    element_id: str,
    action: str,
    event_kind: EventKind = "button_clicked",
) -> Handler[Event]:
    """Wrap one handler in a one-item ``RemoteDispatchGroup``.

    The returned callable remains compatible with existing call sites,
    but the transport wrapper is the grouped form used for the Display
    copy: one event bucket, one remote message, one authoritative Hub
    dispatch.

    Parameters
    ----------
    inner:
        The real handler being wrapped. Captured but never called
        on the Display side — execution happens on the Hub.
    send:
        The Display's socket-write callable.
    element_id:
        The element this handler is bound to.
    action:
        The action string for the ``RemoteEventHandlerInvocation``
        (typically ``element_id`` or a catalog-derived name).
    event_kind:
        The event kind discriminator for Hub-side dispatch.
    """
    return RemoteDispatchGroup(
        handlers=(inner,),
        send=send,
        element_id=element_id,
        action=action,
        event_kind=event_kind,
    )
