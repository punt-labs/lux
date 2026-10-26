"""StoreLock — the store's single reader/writer mutual-exclusion slot.

The Hub store has exactly one reader — the replicator's snapshot — and many
writers: the mutation tools and the click dispatch. A read/write lock exists to
let readers run concurrently, but with a single reader the only exclusion that
can ever fire is reader-versus-writer, so one reentrant slot captures it. The
slot is reentrant because a write path nests — ``replace_scene`` calls ``apply``,
and an observer cascade re-enters ``apply`` — and a nesting writer must never
deadlock against itself.

``read()`` and ``write()`` hand back the same lock: naming the two sides documents
intent at the call site while a single reentrant slot enforces the one exclusion that
matters. The lock is its own context manager, not a generator-based one, so an
exception raised inside a held block — ``HubOwnershipError`` and friends —
propagates natively, without a re-raise layer reassigning its traceback. Its guard
counts, per thread, the holds that thread has made (:class:`StoreGuard`), which is
what lets the rule that no dial socket lock is taken under it be enforced
(:class:`~punt_lux.domain.hub.lock_discipline.LockDiscipline`).
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.guard_registry import GuardRegistry
from punt_lux.domain.hub.lock_discipline_error import LockDisciplineError

if TYPE_CHECKING:
    from types import TracebackType

__all__ = ["StoreGuard", "StoreLock"]


class _Held(threading.local):
    """How many times the current thread holds one guard."""

    depth: int = 0


@final
class StoreGuard:
    """The context manager of the store lock: it holds the lock and counts its holders.

    The count is per thread and per guard, and only this class changes it, so it is
    the number of holds this thread has made and not yet let go, whatever else runs.
    Letting go of a lock this thread does not hold is a programmer error and raises.
    """

    _lock: threading.RLock
    _held: _Held
    __slots__ = ("__weakref__", "_held", "_lock")

    def __new__(cls, lock: threading.RLock) -> Self:
        self = super().__new__(cls)
        self._lock = lock
        self._held = _Held()
        GuardRegistry.register(self)
        return self

    def holds_here(self) -> bool:
        """Whether the current thread holds this lock."""
        return self._held.depth > 0

    def __enter__(self) -> bool:
        acquired = self._lock.acquire()
        self._held.depth += 1
        return acquired

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._held.depth == 0:
            msg = "a store lock was released by a thread that does not hold it"
            raise LockDisciplineError(msg)
        self._held.depth -= 1
        self._lock.release()


@final
class StoreLock:
    """Reentrant mutual exclusion between the one reader and every writer.

    ``read()`` is held only long enough to copy a scene's state out for a
    resend; ``write()`` is held across a whole mutation so no reader observes a
    torn tree. The two never nest across the boundary, so the store lock and the
    client send lock are never held at once.
    """

    _guard: StoreGuard
    __slots__ = ("_guard",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._guard = StoreGuard(threading.RLock())
        return self

    def read(self) -> StoreGuard:
        """Hold the lock while copying scene state out for a resend."""
        return self._guard

    def write(self) -> StoreGuard:
        """Hold the lock across a mutation so no reader sees a torn tree."""
        return self._guard
