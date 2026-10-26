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
propagates natively, without a re-raise layer reassigning its traceback. It records
that the thread holds it (:class:`~punt_lux.domain.hub.lock_discipline.
LockDiscipline`), which is what lets the rule that no dial socket lock is taken under
it be enforced.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.lock_discipline import LockDiscipline

if TYPE_CHECKING:
    from types import TracebackType

__all__ = ["StoreGuard", "StoreLock"]


@final
class StoreGuard:
    """The context manager of the store lock: it holds the lock and notes the holder."""

    _lock: threading.RLock
    __slots__ = ("_lock",)

    def __new__(cls, lock: threading.RLock) -> Self:
        self = super().__new__(cls)
        self._lock = lock
        return self

    def __enter__(self) -> bool:
        acquired = self._lock.acquire()
        LockDiscipline.store_taken()
        return acquired

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        LockDiscipline.store_released()
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
