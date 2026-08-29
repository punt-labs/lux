"""BoardWork — one click's work: what to load, where to push it, and the clock.

The three travel together through every phase of a click — the answer, the load
behind it, the push that ends it — so they go as one object rather than three
parameters, and no state in :mod:`punt_lux.applets.board_cache` holds a client.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from punt_lux.applets.board_load import BoardLoad, BoardRequest
    from punt_lux.applets.board_ops import BoardOps
    from punt_lux.applets.board_read import BoardRead
    from punt_lux.applets.built_board import BuiltBoard
    from punt_lux.applets.latency import ClickLatency

__all__ = ["BoardWork"]


@final
class BoardWork:
    """The board to load, the client to push it to, and the clock timing both."""

    _client: BoardOps
    _latency: ClickLatency
    _load: BoardLoad
    __slots__ = ("_client", "_latency", "_load")

    def __new__(cls, load: BoardLoad, client: BoardOps, latency: ClickLatency) -> Self:
        self = super().__new__(cls)
        self._load = load
        self._client = client
        self._latency = latency
        return self

    def stage(self, name: str) -> AbstractContextManager[None]:
        """Time one stage of this click under ``name``."""
        return self._latency.stage(name)

    def note(self, said: str) -> None:
        """Say what the stage now being timed did, beside its figure."""
        self._latency.note(said)

    def raise_frame(self) -> None:
        """Bring the board's frame forward, for a click that pushes either way."""
        self._load.showing(self._client)

    def showing(self) -> bool:
        """Raise the board's frame; say whether a board is up already."""
        return self._load.showing(self._client)

    def issues(self) -> BoardRead:
        """Read the issues, noting where the run's time went, or raise."""
        self.note((read := self._load.issues()).summary())
        return read

    def board(self, read: BoardRead) -> BuiltBoard:
        """Build the board those issues make, at the place their read began."""
        return self._load.board(read)

    def placeholder(self) -> BoardRequest:
        """The scene to open with when there is no board to show yet."""
        return self._load.placeholder()

    def unavailable(self, reason: str) -> BoardRequest:
        """The red message saying why there is no board."""
        return self._load.unavailable(reason)

    def push(self, request: BoardRequest) -> None:
        """Install a board through this click's client."""
        self._load.push(self._client, request)
