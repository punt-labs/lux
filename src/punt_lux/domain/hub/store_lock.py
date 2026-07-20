"""StoreLock — the store's single reader/writer mutual-exclusion slot.

The Hub store has exactly one reader — the replicator's snapshot — and many
writers: the mutation tools and the click dispatch. A read/write lock exists to
let readers run concurrently, but with a single reader the only exclusion that
can ever fire is reader-versus-writer, so one reentrant slot captures it. The
slot is reentrant because a write path nests — ``replace_scene`` calls ``apply``,
and an observer cascade re-enters ``apply`` — and a nesting writer must never
deadlock against itself.

``read()`` and ``write()`` hand back the same underlying lock: naming the two
sides documents intent at the call site while a single reentrant slot enforces
the one exclusion that matters. The lock is returned directly rather than wrapped
in a generator context manager so an exception raised inside a held block —
``HubOwnershipError`` and friends — propagates natively, without a re-raise
layer reassigning its traceback.
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

__all__ = ["StoreLock"]


class StoreLock:
    """Reentrant mutual exclusion between the one reader and every writer.

    ``read()`` is held only long enough to copy a scene's state out for a
    resend; ``write()`` is held across a whole mutation so no reader observes a
    torn tree. The two never nest across the boundary, so the store lock and the
    client send lock are never held at once.
    """

    _lock: threading.RLock
    __slots__ = ("_lock",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._lock = threading.RLock()
        return self

    def read(self) -> AbstractContextManager[bool]:
        """Hold the lock while copying scene state out for a resend."""
        return self._lock

    def write(self) -> AbstractContextManager[bool]:
        """Hold the lock across a mutation so no reader sees a torn tree."""
        return self._lock
