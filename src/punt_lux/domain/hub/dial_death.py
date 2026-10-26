"""DialDeath -- the evidence that the display ended a dial: what it still owed.

When the display ends a dial, the scenes written to that dial and never acked are the
suspects: they are what the display held when it died. The dial's own ledger is the
only evidence, so whoever discovers the death (the reader, the keepalive, an MCP tool's
redial, the replicator's send) leaves the same record on the dial that died, which the
replicator charges once. A dial the Hub ended, or one that owed nothing, leaves none.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from punt_lux.domain.ids import SceneId

__all__ = ["DialDeath"]


@dataclass(frozen=True, slots=True)
class DialDeath:
    """One display-ended dial: the scenes it owed acks for, and where it was."""

    suspects: frozenset[SceneId]
    endpoint: str  # the display's label, for the quarantine record's reason

    def __post_init__(self) -> None:
        if not self.suspects:
            msg = "a death with no suspects charges nothing, so it is never recorded"
            raise ValueError(msg)

    @property
    def reason(self) -> str:
        """Why the suspects were charged, as a quarantine record states it."""
        return f"the display at {self.endpoint} ended the connection"
