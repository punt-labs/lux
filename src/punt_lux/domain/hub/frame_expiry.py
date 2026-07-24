"""FrameExpiry — per-frame deadlines and the due set, on a monotonic clock.

A frame may carry an agent-set time-to-live: shown with a ``ttl_seconds``, it is
removed once that many seconds pass with no re-show refreshing it. This component
owns only the bookkeeping — ``frame_id`` to a monotonic deadline — and the two
questions the Hub asks of it: which frames are due now, and how long until the
soonest one. It holds no lock and touches no store; the Hub drives it under the
store lock so arming a deadline and expiring a frame stay atomic against a
concurrent re-show, and so this one small object stays trivially testable with a
fake clock and model-checkable in isolation.

Time is monotonic, not wall-clock: a TTL is a duration, so it must be immune to
clock adjustments. ``claim_due`` removes as it returns, keeping "is it due?" and
"take it" a single indivisible decision — a re-arm that lands after a claim
starts a fresh countdown rather than re-firing a deadline already consumed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["FrameExpiry"]


@final
class FrameExpiry:
    """Frame deadlines on a monotonic clock: arm, disarm, and claim the due set."""

    _deadlines: dict[str, float]
    _now: Callable[[], float]
    __slots__ = ("_deadlines", "_now")

    def __new__(cls, now: Callable[[], float]) -> Self:
        self = super().__new__(cls)
        self._deadlines = {}
        self._now = now
        return self

    def arm(self, frame_id: str, ttl_seconds: float) -> None:
        """Set ``frame_id``'s deadline ``ttl_seconds`` out, replacing any prior one."""
        self._deadlines[frame_id] = self._now() + ttl_seconds

    def disarm(self, frame_id: str) -> None:
        """Drop ``frame_id``'s deadline so it never expires. Idempotent."""
        self._deadlines.pop(frame_id, None)

    def set_deadline(self, frame_id: str, ttl_seconds: float | None) -> None:
        """Arm ``frame_id`` at ``ttl_seconds``, or disarm it when ttl is absent.

        A re-show carries the caller's fresh intent: a new TTL replaces the old
        deadline, and no TTL (``ttl_seconds is None`` — the genuine "permanent"
        state, PY-TS-14) makes the frame permanent, matching whole-UI-resend
        semantics where the latest show wins.
        """
        if ttl_seconds is None:
            self.disarm(frame_id)
        else:
            self.arm(frame_id, ttl_seconds)

    def claim_due(self) -> frozenset[str]:
        """Remove and return every frame whose deadline has passed at the clock now.

        Claim-and-remove in one call is what makes the expiry decision atomic under
        the caller's lock: a frame is returned exactly once and its deadline is
        gone, so a re-arm after the claim starts a fresh countdown instead of
        re-firing a deadline already consumed.
        """
        now = self._now()
        due = frozenset(f for f, deadline in self._deadlines.items() if deadline <= now)
        for frame_id in due:
            del self._deadlines[frame_id]
        return due

    def seconds_until_next(self) -> float | None:
        """Return the wait until the soonest deadline, or None when none are armed.

        None is the documented "idle" contract (PY-TS-14): no frame is armed, so a
        caller may wait for other work rather than poll. An already-passed deadline
        clamps to ``0.0`` so a caller sweeps at once instead of sleeping a negative
        interval.
        """
        if not self._deadlines:
            return None
        return max(0.0, min(self._deadlines.values()) - self._now())
