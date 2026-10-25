"""ScreenshotQueue -- the one screenshot waiting for the next swap, and its requester.

A screenshot can only be taken after a buffer swap, so a request waits until the
next one. One waits at a time; a request that arrives while another waits is
answered at once with an error, never allowed to replace it: the requester of a
replaced request would wait out its whole timeout for a reply that never comes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.protocol import ScreenshotResponse

if TYPE_CHECKING:
    import socket
    from collections.abc import Callable

    from punt_lux.display.socket_server import SocketListener

__all__ = ["ScreenshotQueue"]


@final
class ScreenshotQueue:
    """Holds the requester of the screenshot taken at the next swap."""

    _listener: SocketListener
    _capture: Callable[[], ScreenshotResponse]
    _waiting: socket.socket | None  # None = no screenshot waits for the next swap
    __slots__ = ("_capture", "_listener", "_waiting")

    def __new__(
        cls, listener: SocketListener, capture: Callable[[], ScreenshotResponse]
    ) -> Self:
        self = super().__new__(cls)
        self._listener = listener
        self._capture = capture
        self._waiting = None
        return self

    def request(self, sock: socket.socket) -> None:
        """Take a screenshot for ``sock`` at the next swap, or refuse it at once."""
        if self._waiting is not None:
            busy = ScreenshotResponse(
                error="a screenshot is already waiting for the next frame"
            )
            self._listener.reply_to_client(sock, busy)
            return
        self._waiting = sock

    def after_swap(self) -> None:
        """Answer the waiting request, if any, with the frame just painted."""
        sock = self._waiting
        if sock is None:
            return
        self._waiting = None
        self._listener.reply_to_client(sock, self._capture())
