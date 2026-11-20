"""What one frame observed about terminal output, and whether the loop may sleep."""

from __future__ import annotations

from dataclasses import dataclass

QUIET_BEFORE_IDLE_S = 0.25


@dataclass(frozen=True, slots=True)
class IdlingDecision:
    """One frame's terminal observations.

    The daemon socket is not in the windowing system's wait set, so a sleeping
    loop notices terminal bytes only on the idle timer. A live session
    therefore never idles: a TUI streaming in bursts with sub-second gaps
    would otherwise oscillate in and out of idle and pay that delay on every
    repaint.
    """

    busy: bool
    has_live_session: bool
    quiet_for: float

    @property
    def should_idle(self) -> bool:
        return (
            not self.has_live_session
            and not self.busy
            and self.quiet_for > QUIET_BEFORE_IDLE_S
        )
