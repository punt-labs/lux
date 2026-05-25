"""Remote-dispatch wrapper for two-tier handler systems.

When the Hub and Display are separate processes, the display-side
element factory wraps every ``ButtonClicked`` handler in
``remote_dispatch`` so that ``element.fire(ButtonClicked(...))`` on the
Display side sends a ``RemoteEventHandlerInvocation`` to the Hub
instead of executing the handler body. On the Hub side, the same
handlers are decoded without wrapping and execute directly.

One event type (``ButtonClicked``) on both tiers. The wrapping is the
distribution concern — handler code, ``element.fire()``, and the
catalog factories are identical on both sides.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from punt_lux.protocol.messages.remote_invocation import RemoteEventHandlerInvocation

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.domain.interaction import ButtonClicked

__all__ = ["remote_dispatch"]

_log = logging.getLogger(__name__)

type SendFn = Callable[[RemoteEventHandlerInvocation], None]


def remote_dispatch(
    send: SendFn,
    element_id: str,
    action: str,
) -> Callable[[ButtonClicked], None]:
    """Return a handler that wraps a ``ButtonClicked`` dispatch.

    The returned callable accepts a ``ButtonClicked`` event and sends
    an ``RemoteEventHandlerInvocation`` over the socket instead of
    executing catalog logic locally. The Hub receives the message,
    resolves the element from ``HubDisplay``, and fires the real
    (unwrapped) handler.

    Parameters
    ----------
    send:
        The Display's socket-write callable.
    element_id:
        The element this handler is bound to.
    action:
        The action string for the ``RemoteEventHandlerInvocation``
        (typically ``element_id`` or a catalog-derived name).
    """

    def _handler(_event: ButtonClicked) -> None:
        _log.debug(
            "remote_dispatch sending element_id=%s action=%s",
            element_id,
            action,
        )
        send(
            RemoteEventHandlerInvocation(
                element_id=element_id,
                action=action,
                ts=time.time(),
                value=True,
            )
        )

    return _handler
