"""ConnectionClosedError -- the display connection is not open, or was closed."""

from __future__ import annotations

__all__ = ["ConnectionClosedError"]


class ConnectionClosedError(ConnectionError):
    """The connection to the display is not open, or the display closed it.

    One error for every way a read or write finds the socket gone, so a caller
    need not tell "never opened", "closed under me" and "closed by the display"
    apart by message. It is an ``OSError``: a lost connection is a failed send.
    """
