"""ClientIdentityBook -- fd-keyed declared-identity tracking.

Split out of ``SocketListener`` (DES-090 W8): three fd-keyed dicts (name,
kind, connect time) and the single-owner preemption lookup (DES-068) that
reads them are one cohesive concern -- declared identity bookkeeping --
distinct from the socket I/O ``SocketListener`` itself owns.
"""

from __future__ import annotations

from typing import Literal, Self, final

__all__ = ["ClientIdentityBook"]


@final
class ClientIdentityBook:
    """Track each fd's declared kind, display name, and connect time."""

    _names: dict[int, str]
    _kinds: dict[int, Literal["hub", "test"]]
    _connect_times: dict[int, float]
    __slots__ = ("_connect_times", "_kinds", "_names")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._names = {}
        self._kinds = {}
        self._connect_times = {}
        return self

    @property
    def names(self) -> dict[int, str]:
        """Return fd-to-display-name mapping."""
        return self._names

    @property
    def connect_times(self) -> dict[int, float]:
        """Return fd-to-connect-timestamp mapping."""
        return self._connect_times

    def register(
        self, fd: int, *, kind: Literal["hub", "test"], name: str, connect_time: float
    ) -> None:
        """Record a client's declared kind, display name, and connect timestamp."""
        self._names[fd] = name
        self._kinds[fd] = kind
        self._connect_times[fd] = connect_time

    def kind_of(self, fd: int) -> Literal["hub", "test"] | None:
        """Return the declared kind for ``fd``, or ``None`` before it identifies."""
        return self._kinds.get(fd)

    def hub_fd_for(self, name: str) -> int | None:
        """Return the live fd currently declaring ``kind="hub"`` with this name.

        ``None`` when no such connection exists -- the ordinary case once a
        superseded Hub's socket has already closed on its own. Single-owner
        preemption (DES-068) uses this to find (and evict) a predecessor
        before recording a new claimant, so at most one ever holds the name.
        """
        for candidate_fd, kind in self._kinds.items():
            if kind == "hub" and self._names.get(candidate_fd) == name:
                return candidate_fd
        return None

    def discard(self, fd: int) -> None:
        """Drop all identity state for ``fd`` (a no-op if never registered)."""
        self._names.pop(fd, None)
        self._kinds.pop(fd, None)
        self._connect_times.pop(fd, None)
