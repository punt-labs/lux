"""LockDiscipline -- the one rule about the store lock that a comment cannot keep.

A Hub handler fires under the store write lock, and the lock that guards a dial's
socket is never taken while the store lock is held: the first would let a handler
walk the element index while an agent's ``show`` mutates it, and the second closes a
cycle with any path that holds the socket lock and then wants the store. The store lock
records that it is held by the current thread; the two doors check it and raise, so
a break is a failure the first time it runs, not a deadlock under load.
"""

from __future__ import annotations

import threading
from typing import final

__all__ = ["LockDiscipline", "LockDisciplineError"]


class LockDisciplineError(RuntimeError):
    """A lock was taken, or a handler fired, outside the order the Hub keeps."""


class _Held(threading.local):
    """How many times the current thread holds the store lock."""

    depth: int = 0


@final
class LockDiscipline:
    """Which locks the current thread holds, and what that forbids."""

    _held = _Held()
    __slots__ = ()

    @classmethod
    def store_taken(cls) -> None:
        """Note that the current thread took the store lock (it is reentrant)."""
        cls._held.depth += 1

    @classmethod
    def store_released(cls) -> None:
        """Note that the current thread released the store lock once."""
        cls._held.depth -= 1

    @classmethod
    def holds_store(cls) -> bool:
        """Whether the current thread holds the store lock."""
        return cls._held.depth > 0

    @classmethod
    def require_store(cls, what: str) -> None:
        """Raise unless the current thread holds the store lock for ``what``."""
        if not cls.holds_store():
            msg = f"{what} requires the store write lock, which this thread lacks"
            raise LockDisciplineError(msg)

    @classmethod
    def forbid_store(cls, what: str) -> None:
        """Raise if the current thread holds the store lock while taking ``what``."""
        if cls.holds_store():
            msg = f"{what} must never be taken while the store lock is held"
            raise LockDisciplineError(msg)
