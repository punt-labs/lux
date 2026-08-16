"""QuarantineRecord — the evidence a quarantined scene carries on its entry.

A scene is quarantined after repeated Display deaths are attributed to it
(:mod:`.crash_attribution`). Quarantine is not a bare flag: this record is the
evidence an agent needs to understand and fix what it did — how many attributed
deaths, when the most recent one landed, and, when the Hub captured the
underlying exception, the renderer or transport error that surfaced the death
(a renderer TypeError the Display flushed, or an OSError/BlockingIOError the
Hub's send/probe caught). The record is owned by the store's scene entry
(:class:`~punt_lux.domain.hub.quarantine_registry.QuarantineRegistry`), not a
parallel status channel.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = ["QuarantineRecord"]


@dataclass(frozen=True, slots=True)
class QuarantineRecord:
    """Why a scene stopped being replicated, and what to tell its owner.

    ``status`` is a self-describing discriminant (mirrors ``OpError.kind`` and
    ``SceneShown.kind`` elsewhere in this codebase) rather than the record's
    mere presence silently meaning "quarantined" — a reader of a bare
    ``QuarantineRecord`` value knows what it is without consulting where it
    came from.
    """

    status: Literal["quarantined"] = "quarantined"
    death_count: int = 0
    last_death_at: float = 0.0
    # Populated when the Hub captured the exception that surfaced the death —
    # a renderer error the Display managed to flush, or a socket-level failure
    # (OSError/BlockingIOError) the send or liveness probe caught. Attribution
    # never depends on one arriving (display-crash-quarantine.md Question 1 —
    # a crash unwinds the frame with no reliable flush point), so None is a
    # normal outcome for a scene attributed to a purely correlational death.
    render_error: str | None = None

    def describe(self, scene_id: str) -> str:
        """Return the agent-facing prose explaining why ``scene_id`` went dark."""
        base = (
            f"scene {scene_id!r} is quarantined after {self.death_count} "
            f"attributed Display deaths (most recent at {self.last_death_at:.3f}); "
            "re-show the scene with a fixed tree to lift the quarantine"
        )
        if self.render_error is None:
            return base
        return f"{base}; last renderer or transport error: {self.render_error}"

    def to_payload(self) -> dict[str, object]:
        """Return the wire payload this record publishes to scene subscribers."""
        return {
            "status": self.status,
            "death_count": self.death_count,
            "last_death_at": self.last_death_at,
            "render_error": self.render_error,
        }
