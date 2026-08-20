"""QuarantineInfo — the read shape for a scene's quarantine record."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from punt_lux.domain.hub.quarantine_record import QuarantineRecord

__all__ = ["QuarantineInfo"]


class QuarantineInfo(BaseModel):
    """Why a scene stopped being replicated: attributed deaths, when, and any error.

    Mirrors :class:`~punt_lux.domain.hub.quarantine_record.QuarantineRecord`, the
    Hub-side value it is built from — this is the wire read shape, not the store's
    own record.
    """

    model_config = ConfigDict(frozen=True)

    status: Literal["quarantined"] = "quarantined"
    death_count: int
    last_death_at: float
    # Populated only when the Display managed to report a render error before
    # dying; absence means none was ever received, not that none occurred.
    render_error: str | None = None

    @classmethod
    def of(cls, record: QuarantineRecord) -> Self:
        """Build the read shape from a Hub-side :class:`QuarantineRecord`."""
        return cls(
            death_count=record.death_count,
            last_death_at=record.last_death_at,
            render_error=record.render_error,
        )
