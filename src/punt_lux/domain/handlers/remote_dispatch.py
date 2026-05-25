"""Remote-dispatch decorator for two-tier handler systems.

When the Hub and Display are separate processes, the Display wraps
every handler in ``remote_dispatch`` so that ``element.fire()`` on
the Display side routes execution to the Hub instead of running the
handler body locally. The distribution concern is encapsulated here;
handler code, ``element.fire()``, and the catalog factories are
identical on both sides.

Pre-optimization default: every handler routes to Hub.
Post-optimization: selective handlers can be flagged for local
execution (not in PR 4 scope).
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from punt_lux.protocol.messages.interaction import InteractionMessage

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.event_protocol import Event

__all__ = ["remote_dispatch"]

_log = logging.getLogger(__name__)

type SendFn = Callable[[InteractionMessage], None]


def remote_dispatch(
    send: SendFn,
    element_id: str,
    action: str,
) -> Callable[[Event], None]:
    """Return a handler that routes the event to the Hub via ``send``.

    The returned callable satisfies ``Handler[E]`` — it accepts the
    event and sends an ``InteractionMessage`` over the socket instead
    of executing catalog logic locally. The Hub receives the message,
    resolves the element from ``HubDisplay``, and fires the real
    (unwrapped) handler.

    Parameters
    ----------
    send:
        The Display's socket-write callable (same path
        ``ButtonRenderer._emit_event`` uses today).
    element_id:
        The element this handler is bound to.
    action:
        The action string for the ``InteractionMessage``
        (typically ``element_id`` or a catalog-derived name).
    """

    def _handler(_event: Event) -> None:
        _log.debug(
            "remote_dispatch sending element_id=%s action=%s",
            element_id,
            action,
        )
        send(
            InteractionMessage(
                element_id=element_id,
                action=action,
                ts=time.time(),
                value=True,
            )
        )

    return _handler
