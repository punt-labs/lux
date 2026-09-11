"""CallbackKey -- the ``(element_id, action)`` pair a DisplayLink callback answers to.

Extracted from :class:`DisplayLink` (PY-OO-5): the pair is constructed and
compared identically wherever a callback is registered, removed, or
dispatched (``on_event``, ``remove_callback``, ``_dispatch``), so it is a
value in its own right rather than an anonymous ``tuple[str, str]`` repeated
at every call site.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

__all__ = ["CallbackKey"]


@final
@dataclass(frozen=True, slots=True)
class CallbackKey:
    """The ``(element_id, action)`` pair identifying one registered callback."""

    element_id: str
    action: str
