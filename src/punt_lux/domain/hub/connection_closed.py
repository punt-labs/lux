"""ConnectionClosedError -- a dial the display connection held was closed."""

from __future__ import annotations

from typing import Literal

__all__ = ["ConnectionClosedError", "HubRetiredError", "RetireCause"]

# Who ended a dial: the display (it closed the stream, or a read or write failed on
# the socket) or the Hub (its own policy: a query timeout, a reply out of order, a
# write interrupted by something other than a socket failure, a deliberate close).
# Only the first is evidence the display died.
type RetireCause = Literal["display", "hub"]


class ConnectionClosedError(ConnectionError):
    """A dial the connection held is closed, under a request or by the display.

    One error for every way a read or write finds the socket gone, so a caller
    need not tell "closed under me" and "closed by the display" apart by message.
    A connection that never held a dial is not this: it raises
    :class:`~punt_lux.domain.hub.display_not_connected.DisplayNotConnectedError`.
    It is an ``OSError``: a lost connection is a failed send.
    """


class HubRetiredError(ConnectionClosedError):
    """The Hub ended this dial by its own policy; the display did not die.

    A query that timed out, a reply that came out of order, a write interrupted
    by something other than a socket failure, and the Hub's own close all end a
    dial this way. A sender that finds a dial ended this way has learned nothing
    about the display, so it must not be blamed on whatever the sender was
    sending. A dial the display ended (it closed the stream, reset the
    connection, sent a frame that cannot be decoded, or stopped reading until a
    send timed out) is a plain :class:`ConnectionClosedError`.
    """
