"""Refusals by the judge: a write the Hub will not make, whichever door it came by.

Both are :class:`~punt_lux.domain.handler_writes.WriteRefusedError`, which an observer
fan-out lets through after the other observers have run, so the transaction that woke
the observer rolls back and the agent is told why:

- :class:`NestingExceededError` -- a write that would nest an element's wire form past
  the cap.
- :class:`UnheldTargetError` -- a write to an element no scene the Hub holds contains.
"""

from __future__ import annotations

from dataclasses import dataclass

from punt_lux.domain.handler_writes import WriteRefusedError

__all__ = ["NestingExceededError", "UnheldTargetError"]


@dataclass(frozen=True, slots=True)
class NestingExceededError(WriteRefusedError, ValueError):
    """Raised when a write would nest an element's wire form past the cap.

    The write seam raises it for an install and a store-level property write; the
    ``update`` path reports the same ``reason`` as a ``WriteRejected`` and the install
    door as a rejection, so the agent reads one message whichever door it used.
    """

    reason: str

    def __str__(self) -> str:
        return self.reason


@dataclass(frozen=True, slots=True)
class UnheldTargetError(WriteRefusedError, LookupError):
    """Raised when a write names an element no scene the Hub holds contains.

    Its scene, and so its nesting cap, cannot be known: the judge refuses it.
    """

    element_id: str

    def __str__(self) -> str:
        return (
            f"write target {self.element_id!r} is installed in no scene the Hub holds"
        )
