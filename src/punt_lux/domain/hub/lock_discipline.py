"""LockDiscipline -- the one rule about the store lock that a comment cannot keep.

A Hub handler fires under the store write lock, and the lock that guards a dial's
socket is never taken while the store lock is held: the first would let a handler
walk the element index while an agent's ``show`` mutates it, and the second closes a
cycle with any path that holds the socket lock and then wants the store. Each store
lock counts, per thread, how many times that thread holds it
(:class:`~punt_lux.domain.hub.store_lock.StoreGuard`), registered in
:class:`~punt_lux.domain.hub.guard_registry.GuardRegistry`; the doors here only ask, and
raise, so a break is a failure the first time it runs, not a deadlock under load. The
count is no one's to set from outside the guard.
"""

from __future__ import annotations

from typing import final

from punt_lux.domain.hub.guard_registry import GuardRegistry
from punt_lux.domain.hub.lock_discipline_error import LockDisciplineError

__all__ = ["LockDiscipline"]


@final
class LockDiscipline:
    """What the current thread's hold on the store lock requires and forbids."""

    __slots__ = ()

    @classmethod
    def holds_store(cls) -> bool:
        """Whether the current thread holds any store lock."""
        return GuardRegistry.is_held()

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
