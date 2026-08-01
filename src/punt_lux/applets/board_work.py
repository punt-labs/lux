"""BoardWork — one click's work: what to load, where to push it, and the clock.

The three travel together through every phase of a click — the answer, the load
behind it, the push that ends it — so they travel as one object rather than as
three parameters threaded down each path. It is also what keeps the two states in
:mod:`punt_lux.applets.board_cache` from reaching through a load to a client:
they are handed the work and tell it what to do.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from contextlib import AbstractContextManager

    from punt_lux.applets.board_load import BoardLoad, BoardRequest
    from punt_lux.applets.latency import ClickLatency
    from punt_lux.apps.beads_load import BeadsLoad
    from punt_lux.rest_client import LuxRestClient

__all__ = ["BoardWork"]


@final
class BoardWork:
    """The board to load, the client to push it to, and the clock timing both."""

    _client: LuxRestClient
    _latency: ClickLatency
    _load: BoardLoad
    __slots__ = ("_client", "_latency", "_load")

    def __new__(
        cls, load: BoardLoad, client: LuxRestClient, latency: ClickLatency
    ) -> Self:
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

    def showing(self) -> bool:
        """Raise the board's frame; say whether the user already has the board."""
        return self._load.showing(self._client)

    def issues(self) -> BeadsLoad:
        """Read the issues, noting where the run's time went, or raise."""
        self.note((loaded := self._load.issues()).summary())
        return loaded

    def board(self, issues: BeadsLoad) -> BoardRequest:
        """Build the board those issues make."""
        return self._load.board(issues)

    def fresh(self) -> BoardRequest:
        """Read the issues and build their board, for a click not timing the two."""
        return self._load.board(self.issues())

    def placeholder(self) -> BoardRequest:
        """The scene to open with when there is no board to show yet."""
        return self._load.placeholder()

    def unavailable(self, reason: str) -> BoardRequest:
        """The red message saying why there is no board."""
        return self._load.unavailable(reason)

    def push(self, request: BoardRequest) -> None:
        """Install a board through this click's client."""
        self._load.push(self._client, request)
