"""Refusals by the judge: a write the Hub will not make, whichever door it came by.

Both are :class:`~punt_lux.domain.handler_writes.WriteRefusedError`, which an observer
fan-out lets through after the other observers have run, so the transaction that woke
the observer rolls back and the agent is told why:

- :class:`NestingExceededError` -- a write that would nest an element's wire form past
  the cap.
- :class:`UnheldTargetError` -- a write to an element no scene the Hub holds contains.
"""

from __future__ import annotations

from typing import Self

from punt_lux.domain.handler_writes import WriteRefusedError

__all__ = ["NestingExceededError", "UnheldTargetError"]


class NestingExceededError(WriteRefusedError, ValueError):
    """Raised when a write would nest an element's wire form past the cap.

    The write seam raises it for an install and a store-level property write; the
    ``update`` path reports the same ``reason`` as a ``WriteRejected`` and the install
    door as a rejection, so the agent reads one message whichever door it used.

    A plain exception class, not a frozen dataclass: ``contextlib`` sets
    ``__traceback__`` on whatever passes through a ``@contextmanager``, which a
    frozen instance refuses.
    """

    _reason: str

    def __new__(cls, reason: str) -> Self:
        self = super().__new__(cls, reason)
        self._reason = reason
        return self

    @property
    def reason(self) -> str:
        """Why the write was refused, in the agent's terms."""
        return self._reason

    def __str__(self) -> str:
        return self._reason


class UnheldTargetError(WriteRefusedError, LookupError):
    """Raised when a write names an element no scene the Hub holds contains.

    Its scene, and so its nesting cap, cannot be known: the judge refuses it.
    """

    _element_id: str

    def __new__(cls, element_id: str) -> Self:
        self = super().__new__(cls, element_id)
        self._element_id = element_id
        return self

    @property
    def element_id(self) -> str:
        """The element the write named."""
        return self._element_id

    def __str__(self) -> str:
        return (
            f"write target {self._element_id!r} is installed in no scene the Hub holds"
        )
