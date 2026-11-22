"""Span — a number of seconds, as a person says it.

Durations are reported to people in several places — how long a client has been
connected, how long its lease runs — and they should read the same way in all of
them. One value class owns that rendering so two callers cannot drift into two
formats.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self, final

__all__ = ["Span"]

_SECONDS_PER_MINUTE = 60
_SECONDS_PER_HOUR = 3600


@final
@dataclass(frozen=True, slots=True)
class Span:
    """A duration in seconds, and the line a person reads it as."""

    seconds: float

    @classmethod
    def of(cls, seconds: float) -> Self:
        """Return the span *seconds* long, floored at zero.

        A negative span is not a shorter one: it is a clock that went backwards,
        and reading it as ``-3s`` would report the clock rather than the fact.
        """
        return cls(max(0.0, seconds))

    def rendered(self) -> str:
        """Render as a person says it: ``45s``, ``12m 05s``, ``3h 07m``."""
        whole = int(self.seconds)
        if whole < _SECONDS_PER_MINUTE:
            return f"{whole}s"
        if whole < _SECONDS_PER_HOUR:
            return f"{whole // _SECONDS_PER_MINUTE}m {whole % _SECONDS_PER_MINUTE:02d}s"
        minutes = whole % _SECONDS_PER_HOUR // _SECONDS_PER_MINUTE
        return f"{whole // _SECONDS_PER_HOUR}h {minutes:02d}m"
