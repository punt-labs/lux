"""OwnedCondition -- a non-reentrant condition that knows which thread holds it.

A ``*_locked`` method runs only under the lock its caller already holds. The question
"is it held, and by this thread?" cannot be answered by trying the lock (another
thread's hold would pass for the caller's), so the condition records its owner on the
way in and clears it on the way out, as ``StoreGuard`` does for the store lock. A wait
gives the lock up and takes it back, and the record follows.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.lock_discipline_error import LockDisciplineError

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType

__all__ = ["OwnedCondition"]


@final
class OwnedCondition:
    """A condition over one plain lock, and the thread that holds it."""

    _cond: threading.Condition
    # PY-TS-14 OK: None while no thread holds the lock.
    _owner: int | None
    __slots__ = ("_cond", "_owner")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._cond = threading.Condition(threading.Lock())
        self._owner = None
        return self

    def __enter__(self) -> Self:
        self._cond.acquire()
        self._owner = threading.get_ident()
        return self

    def __exit__(
        self,
        _exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _tb: TracebackType | None,
    ) -> None:
        if not self.held_here():
            msg = "a condition was released by a thread that does not hold it"
            raise LockDisciplineError(msg)
        self._owner = None
        self._cond.release()

    def held_here(self) -> bool:
        """Whether the current thread holds the lock."""
        return self._owner == threading.get_ident()

    def wait_for(self, predicate: Callable[[], bool], timeout: float) -> bool:
        """Wait, lock released, until ``predicate`` holds or ``timeout`` passes."""
        self._require_here("wait")
        self._owner = None
        try:
            return self._cond.wait_for(predicate, timeout)
        finally:
            self._owner = threading.get_ident()

    def notify_all(self) -> None:
        """Wake every waiter; the caller holds the lock."""
        self._require_here("notify")
        self._cond.notify_all()

    def _require_here(self, what: str) -> None:
        if not self.held_here():
            msg = f"a condition was asked to {what} by a thread that does not hold it"
            raise LockDisciplineError(msg)
