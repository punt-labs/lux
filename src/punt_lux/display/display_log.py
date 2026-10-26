"""DisplayLog -- the display's bounded record of recent events and errors."""

from __future__ import annotations

import time
from collections import deque
from typing import Any, Literal, Self, final

__all__ = ["DisplayLog", "LogChannel"]

type LogChannel = Literal["events", "errors"]

# Per channel: how many entries are kept, and how many a report returns by default.
_KEPT: dict[LogChannel, int] = {"events": 200, "errors": 100}
_DEFAULT_REPORT: dict[LogChannel, int] = {"events": 50, "errors": 20}


@final
class DisplayLog:
    """Keep the last interaction events and display-side errors, and report them.

    A report never returns more than the channel keeps, however many it is asked for.
    """

    _rings: dict[LogChannel, deque[dict[str, Any]]]
    __slots__ = ("_rings",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._rings = {name: deque(maxlen=kept) for name, kept in _KEPT.items()}
        return self

    def record_event(self, event: dict[str, Any]) -> None:
        """Append an interaction event."""
        self._rings["events"].append(event)

    def record_error(self, severity: str, message: str, context: str = "") -> None:
        """Append a display-side error, stamped with the time it was recorded."""
        self._rings["errors"].append(
            {
                "timestamp": time.time(),
                "severity": severity,
                "message": message,
                "context": context,
            }
        )

    def report(
        self, channel: LogChannel, count: int | None = None, **_kwargs: Any
    ) -> dict[str, Any]:
        """The last ``count`` entries of ``channel`` and how many are buffered."""
        ring = self._rings[channel]
        wanted = min(
            _DEFAULT_REPORT[channel] if count is None else count, ring.maxlen or 0
        )
        return {channel: list(ring)[-wanted:], "total_buffered": len(ring)}
