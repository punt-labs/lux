"""DisplayBusyError -- a request of this kind is already in flight; none was sent."""

from __future__ import annotations

__all__ = ["DisplayBusyError"]


class DisplayBusyError(Exception):
    """The budget ran out waiting for the request lock, so nothing was sent.

    Not a failure of the display: another request of the same kind holds the
    dial. A liveness probe must not read it as a dead display.
    """
