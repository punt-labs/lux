"""ReaderSlot -- the one reader a dial's socket may have at a time.

A dial's frame buffer is fed by one reader at once: its listener thread, or one
caller's inline wait. The slot says which, and makes the others wait or wait on the
sink that reader feeds. It is a leaf lock, held only to read or change the holder,
never while taking another lock or doing I/O; claiming it for a listener waits out
an inline read in flight, so no caller may hold a lock the request model or the
registry shares.
"""

from __future__ import annotations

import contextlib
import threading
from typing import TYPE_CHECKING, Literal, Self, final

if TYPE_CHECKING:
    from collections.abc import Generator

__all__ = ["ReaderSlot"]


@final
class ReaderSlot:
    """Who reads one dial: nobody, its listener thread, or one caller's inline wait."""

    _cond: threading.Condition
    _holder: Literal["none", "listener", "inline"]
    __slots__ = ("_cond", "_holder")

    def __new__(cls, holder: Literal["none", "listener"] = "none") -> Self:
        self = super().__new__(cls)
        self._cond = threading.Condition()
        self._holder = holder
        return self

    @property
    def has_listener(self) -> bool:
        """Whether a listener thread holds the slot.

        A bare load, deliberately without the lock: it is one attribute read,
        advisory, and the lock can be held for an inline read's whole wait, which
        no state-lock holder may queue behind.
        """
        return self._holder == "listener"

    def claim_for_listener(self) -> bool:
        """Take the slot for a listener; ``False`` if a listener already holds it.

        Waits out a caller's inline read in flight: a dial has one reader at a
        time, so two threads never feed one frame buffer.
        """
        with self._cond:
            self._cond.wait_for(lambda: self._holder != "inline")
            if self._holder == "listener":
                return False
            self._holder = "listener"
            return True

    def release_listener(self) -> None:
        """Give the listener's hold back: its thread could not be started."""
        with self._cond:
            if self._holder == "listener":
                self._holder = "none"
                self._cond.notify_all()

    @contextlib.contextmanager
    def inline(self) -> Generator[bool]:
        """Hold the slot for a caller's inline read; yield whether it was free.

        ``False`` means a listener or another caller is reading: wait on the sink,
        which that reader feeds.
        """
        with self._cond:
            granted = self._holder == "none"
            if granted:
                self._holder = "inline"
        try:
            yield granted
        finally:
            if granted:
                with self._cond:
                    self._holder = "none"
                    self._cond.notify_all()
