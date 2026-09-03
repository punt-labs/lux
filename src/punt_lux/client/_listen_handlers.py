"""``ListenHandlers`` -- the callback bundle a persistent listen client needs.

Split out so :meth:`~punt_lux.client.facade.LuxClient.listener` and
:meth:`~punt_lux.client._rest_transport._RestTransport.listener` take one
value object instead of three loose keyword handlers (PY-OO-5, PY-IC-1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from punt_lux.hub_client import CallbackHandler, ConnectHandler, EventHandler

__all__ = ["ListenHandlers"]


@dataclass(frozen=True, slots=True)
class ListenHandlers:
    """The three callbacks a persistent listen client dispatches to."""

    on_callback: CallbackHandler
    on_event: EventHandler
    on_connect: ConnectHandler | None = None
