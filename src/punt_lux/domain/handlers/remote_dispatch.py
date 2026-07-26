"""Remote-dispatch wrappers for two-tier handler systems.

When the Hub and Display are separate processes, the display-side
element factory wraps every interaction handler in ``remote_dispatch``
so that ``element.fire(event)`` on the Display side sends a
``RemoteEventHandlerInvocation`` to the Hub instead of executing the
handler body. On the Hub side, the same handlers are decoded without
wrapping and execute directly.

Every interactive event type crosses on both tiers. The wrapping is the
distribution concern — handler code, ``element.fire()``, and the catalog
factories are identical on both sides.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Self

from punt_lux.domain.container_interaction import (
    HeaderToggled,
    ModalClosed,
    TabChanged,
)
from punt_lux.domain.selection_interaction import RowSelectionChanged
from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.event_kinds import EventKind
    from punt_lux.domain.event_protocol import Event, Handler

__all__ = ["RemoteDispatchGroup"]

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
        # Lazy import avoids circular dependency; interaction.py imports
        # nothing from this module so the cycle is clean.
        from punt_lux.domain.interaction import (  # noqa: PLC0415
            ButtonClicked,
            ValueChanged,
        )

        # Each kind states its own wire payload — a value-per-type match, not
        # an if-ladder — so a new interactive kind is one more ``case``.
        match event:
            case ValueChanged():
                value: object = event.value
            case ButtonClicked():
                value = True
            case HeaderToggled():
                value = event.open
            case TabChanged():
                value = event.tab_id
            case RowSelectionChanged():
                # A set + an anchor: the payload carries both so the Hub can
                # rebuild the selection and name the last-interacted row.
                value = {"row_ids": list(event.row_ids), "anchor": event.anchor}
            case ModalClosed():
                # A dismissal has no payload; the Hub builder ignores the value.
                value = None
            case _:
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
