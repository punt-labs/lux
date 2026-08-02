"""BoardRead — what one run of ``bd`` returned, and where that run began.

A load takes its place in the order before its query runs, because that is when
the issues it will return stop changing — see
:class:`~punt_lux.applets.board_order.BoardOrder`. The place therefore has to
survive the query it was taken ahead of, so it travels with what the query
returned and reaches the board built from it. Nothing downstream can stamp a
board late, because nothing downstream has anything to stamp it with.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.applets.built_board import BuiltBoard

if TYPE_CHECKING:
    from punt_lux.applets.board_load import BoardRequest
    from punt_lux.applets.board_order import BoardOrder
    from punt_lux.apps.beads_load import BeadsLoad
    from punt_lux.apps.beads_result import BeadsResult

__all__ = ["BoardRead"]


@final
class BoardRead:
    """The issues a load read, carrying where the load that read them began."""

    _began: BoardOrder
    _issues: BeadsLoad
    __slots__ = ("_began", "_issues")

    def __new__(cls, issues: BeadsLoad, began: BoardOrder) -> Self:
        self = super().__new__(cls)
        self._issues = issues
        self._began = began
        return self

    @property
    def result(self) -> BeadsResult:
        """The issues that were read, which the board is built from."""
        return self._issues.result

    def summary(self) -> str:
        """Where this run's time went, as the click's line reports it."""
        return self._issues.summary()

    def built(self, request: BoardRequest) -> BuiltBoard:
        """The board these issues make, at the place their read began."""
        return BuiltBoard(request, self._began)
