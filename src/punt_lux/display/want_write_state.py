"""WantWriteState -- the fds whose non-blocking ``recv()`` awaits writability."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    import socket

__all__ = ["WantWriteState"]


class WantWriteState:
    """Fds whose non-blocking ``recv()`` awaits writability (a TLS event, not death).

    A TLS ``recv()`` on a non-blocking socket can raise
    ``ssl.SSLWantWriteError``: OpenSSL needs to *write* (a renegotiation
    record) before it can finish the read. That fd must be watched for
    writability on the next poll, not treated as readable-only. Owned by
    :class:`~punt_lux.display.client_reader.ClientReader`.
    """

    _fds: set[int]
    __slots__ = ("_fds",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._fds = set()
        return self

    def set(self, fd: int, *, wants: bool) -> None:
        """Track (``wants``) or clear (``not wants``) ``fd``'s want-write flag.

        Clearing an untracked fd is a no-op, so the read path can clear
        unconditionally at the top of every read without a membership test.
        """
        (self._fds.add if wants else self._fds.discard)(fd)

    def clear(self) -> None:
        """Drop every tracked fd -- shutdown, not one departure."""
        self._fds.clear()

    def sockets(self, fd_to_client: dict[int, socket.socket]) -> list[socket.socket]:
        """Return the live sockets among the tracked fds, for a write-select.

        A tracked fd with no socket left is skipped: its client departed (closed
        before it could be forgotten) and there is nothing to watch.
        """
        return [fd_to_client[fd] for fd in self._fds if fd in fd_to_client]
