"""LoadingBoard — nothing has been read yet, so the click says what it is doing.

The blank a session starts with. A click from here is the cold one the warm-up
exists to prevent: the user watches "Loading issues…" for however long the query
takes, and the placeholder is the only thing there is to show them meanwhile.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from punt_lux.applets.board_load import BoardRequest
    from punt_lux.applets.board_work import BoardWork

__all__ = ["LoadingBoard"]

# What the line calls this answer. It is a few milliseconds like every other
# answer a click can give, so only the line tells them apart.
_PLACEHOLDER = "loading placeholder"


@final
class LoadingBoard:
    """The placeholder a session opens with, and the wait it stands in for."""

    __slots__ = ()

    def request(self, work: BoardWork) -> BoardRequest:
        """The scene a click opens with when no board has been read yet."""
        return work.placeholder()

    def said(self) -> str:
        """What a click answering with the placeholder says it answered with."""
        return _PLACEHOLDER
