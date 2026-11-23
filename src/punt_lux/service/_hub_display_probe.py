"""Read the Display's own identity over the Hub's existing facts route."""

from __future__ import annotations

from typing import Self

from punt_lux.service._hub_display_facts import HubDisplayFacts
from punt_lux.service._readiness_http import ReadinessHTTP


class HubDisplayProbe:
    """Use anonymous, read-only GET /display without a client-layer dependency."""

    __slots__ = ("_pid", "_timeout")
    _pid: int
    _timeout: float

    def __new__(cls, pid: int, timeout: float) -> Self:
        self = super().__new__(cls)
        self._pid, self._timeout = pid, timeout
        return self

    def connected(self) -> str | None:
        """Require a successful Hub round trip to this exact Display process."""
        try:
            with ReadinessHTTP.open(self._timeout) as connection:
                connection.request("GET", "/display")
                return HubDisplayFacts.identity(connection.getresponse(), self._pid)
        except TimeoutError:
            return None
