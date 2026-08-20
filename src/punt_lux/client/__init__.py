"""The ``LuxClient`` public library surface -- one facade, noun-grouped accessors.

Ships nine accessors: ``scene``, ``frame``, ``menu``, ``session``, ``callback``,
``display``, ``event``, ``error`` -- every noun that reaches the Hub through
the shipped REST surface. ``topic`` (publish/subscribe/receive) and
``callback.pending`` are omitted this cycle: neither has a REST route today
(publish/subscribe/receive have no REST module; callback.pending is
architecturally REST-unreachable because delivery is the listen-leg drain --
see :class:`~punt_lux.commands._ports.CallbackPendingOps`). They land with a
follow-on bead that either wires them through the WebSocket listener or grows
an in-process transport variant.
"""

from __future__ import annotations

from punt_lux.client.callback import CallbackAccessor
from punt_lux.client.display import DisplayAccessor
from punt_lux.client.error import ErrorAccessor
from punt_lux.client.event import EventAccessor
from punt_lux.client.facade import LuxClient
from punt_lux.client.frame import FrameAccessor
from punt_lux.client.menu import MenuAccessor
from punt_lux.client.scene import SceneAccessor
from punt_lux.client.session import SessionAccessor

__all__ = [
    "CallbackAccessor",
    "DisplayAccessor",
    "ErrorAccessor",
    "EventAccessor",
    "FrameAccessor",
    "LuxClient",
    "MenuAccessor",
    "SceneAccessor",
    "SessionAccessor",
]
