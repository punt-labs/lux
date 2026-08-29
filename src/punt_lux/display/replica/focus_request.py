"""The one-shot focus request: at most one frame is ever awaiting it.

Split out of :class:`~punt_lux.display.replica.frame_book.FrameBook`, where the
"clear it if it is this frame's" step was written out at each of the three
places a frame stops being able to take focus — closed, disposed, or cleared
away with the rest. One invariant repeated in three methods is an invariant with
nowhere to live; here it has one.

Focus is a *request*, not a state: the renderer asks once on the render after it
was made and the request is spent, so a frame is focused once and not again.
Only a user gesture ever makes one (DES-065 R8) — a content push never does.
"""

from __future__ import annotations

from typing import Self, final

__all__ = ["FocusRequest"]


@final
class FocusRequest:
    """Hold the at-most-one frame id awaiting focus on the next render."""

    _frame_id: str | None
    __slots__ = ("_frame_id",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._frame_id = None
        return self

    def ask(self, frame_id: str) -> None:
        """Put ``frame_id`` forward for focus, displacing any earlier request."""
        self._frame_id = frame_id

    def consume(self, frame_id: str) -> bool:
        """Return whether ``frame_id`` was awaiting focus, spending the request."""
        if self._frame_id != frame_id:
            return False
        self._frame_id = None
        return True

    def release(self, frame_id: str) -> None:
        """Withdraw the request if it is ``frame_id``'s; leave another's standing.

        A frame that has stopped being painted cannot take focus, so closing,
        disposing, or otherwise putting one away withdraws its claim — and only
        its own.
        """
        if self._frame_id == frame_id:
            self._frame_id = None

    def clear(self) -> None:
        """Withdraw whatever request stands: the workspace it named is gone."""
        self._frame_id = None
