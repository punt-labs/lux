"""GuardRegistry -- which store-lock guards exist, so a thread's holds can be asked.

The dial's socket lock is never taken while any store lock is held by the thread, and
the dial model may name nothing above its own locks. So the question "does this thread
hold a store lock?" is asked of a leaf that knows only that a guard *can say* whether
the current thread holds it; each store lock's guard registers itself here when made.
"""

from __future__ import annotations

import threading
import weakref
from typing import ClassVar, Protocol, final

__all__ = ["GuardRegistry", "Holder"]


class Holder(Protocol):
    """What a registered guard can say: whether the current thread holds its lock."""

    def holds_here(self) -> bool:
        """Whether the current thread holds this guard's lock."""
        ...


@final
class GuardRegistry:
    """The store-lock guards that exist, weakly held."""

    # A ``WeakSet`` is not safe to add to while another thread iterates it, so every
    # touch of it, a registration and the snapshot a question is asked of, is made
    # under this lock. The guards are asked outside it: their answer is thread-local.
    _all: ClassVar[weakref.WeakSet[Holder]] = weakref.WeakSet()
    _lock: ClassVar[threading.Lock] = threading.Lock()
    __slots__ = ()

    @classmethod
    def register(cls, guard: Holder) -> None:
        """Note a guard, so a thread's hold on it is seen by :meth:`is_held`."""
        with cls._lock:
            cls._all.add(guard)

    @classmethod
    def is_held(cls) -> bool:
        """Whether the current thread holds the lock of any registered guard."""
        with cls._lock:
            guards = tuple(cls._all)
        return any(guard.holds_here() for guard in guards)
