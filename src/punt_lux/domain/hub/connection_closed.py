"""ConnectionClosedError -- the display connection is not open, or was closed."""

from __future__ import annotations

from typing import Literal

__all__ = ["ConnectionClosedError", "HubRetiredError", "RetireCause"]

# Who ended a dial: the display (it closed the stream, or a read failed) or the
# Hub (its own policy: a query timeout, a reply out of order, a write that failed,
# a deliberate close). Only the first is evidence the display died.
type RetireCause = Literal["display", "hub"]


class ConnectionClosedError(ConnectionError):
    """The connection to the display is not open, or the display closed it.

    One error for every way a read or write finds the socket gone, so a caller
    need not tell "never opened", "closed under me" and "closed by the display"
    apart by message. It is an ``OSError``: a lost connection is a failed send.
    """


class HubRetiredError(ConnectionClosedError):
    """The Hub retired this dial by its own policy; the display did not die.

    A sender that finds a dial retired this way has learned nothing about the
    display, so it must not be blamed on whatever the sender was sending.
    """
