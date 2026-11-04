"""DialDeath -- the evidence that the display ended a dial: the scenes it may hold.

When the display ends a dial, the scenes written to that dial and never acked are the
suspects, together with any a Hub-ended or unresponsive dial left behind: they are
what the display held when it died. The dial's own ledger and the carried set are the
only evidence, so whoever discovers the death leaves the same record, which the
replicator charges once. A dial the Hub ended, or one that owed nothing, leaves none.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from punt_lux.domain.ids import SceneId

__all__ = ["DialDeath"]


@dataclass(frozen=True, slots=True)
class DialDeath:
    """One display-ended dial: the scenes it may hold, and where it was."""

    suspects: frozenset[SceneId]
    endpoint: str  # the display's label, for the quarantine record's reason
    cause: Literal["display", "unresponsive"]

    def __post_init__(self) -> None:
        if not self.suspects:
            msg = "a death with no suspects charges nothing, so it is never recorded"
            raise ValueError(msg)

    @property
    def reason(self) -> str:
        """Why the suspects were charged, as a quarantine record states it."""
        if self.cause == "unresponsive":
            return f"the display at {self.endpoint} stopped answering"
        return f"the display at {self.endpoint} ended the connection"
