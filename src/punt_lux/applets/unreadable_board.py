"""UnreadableBoard — ``bd`` could not be read, and the reason is what there is.

The blank a failed load leaves behind when there was no board to keep. Every way
the read can fail becomes something the user sees, or a menu entry that answers
with nothing is indistinguishable from one that is broken.

The reason is held rather than pushed on the spot, so that putting it on the
display is the same act as putting a board there — the push region renders
whatever the slot is holding, and a message that came from the slot cannot land
over a board that arrived while the read was failing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from punt_lux.applets.board_load import BoardRequest
    from punt_lux.applets.board_work import BoardWork

__all__ = ["UnreadableBoard"]

# What the line calls a click answered from a state that last failed: the red
# message it already had, not a fresh one this click produced.
_LAST_FAILURE = "last failure"


@final
class UnreadableBoard:
    """No board, and the reason there is none — the red message in its place."""

    _reason: str
    __slots__ = ("_reason",)

    def __new__(cls, reason: str) -> Self:
        self = super().__new__(cls)
        self._reason = reason
        return self

    def request(self, work: BoardWork) -> BoardRequest:
        """The red message naming why there is no board to show."""
        return work.unavailable(self._reason)

    def said(self) -> str:
        """What a click answering with that message says it answered with."""
        return _LAST_FAILURE
