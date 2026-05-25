"""Marker Protocol for events dispatched through ``Element.fire``.

The handler registry on the Element ABC is typed against this Protocol so
``add_handler(event_type, handler)`` rejects callers that mix event
families. Every interaction-event class (``ButtonClicked``, future
``SliderChanged``, ``TextEdited``, ...) satisfies it implicitly — the
Protocol carries no required members, only an identity.

The companion ``Handler[E]`` alias spells the callback shape every
factory in the per-Element handler catalogs must produce.

This Protocol is distinct from the success-event union in
``domain.event``. That union names the outcomes ``Display.apply`` /
``Display.interact`` return; this Protocol names the family of inputs
the per-Element registry dispatches.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

__all__ = ["Event", "Handler"]


@runtime_checkable
class Event(Protocol):
    """Marker Protocol for events dispatched through ``Element.fire``."""


type Handler[E: Event] = Callable[[E], None]
