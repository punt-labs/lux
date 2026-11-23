"""QuarantineInfo — the read shape for a scene's quarantine record."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = ["QuarantineInfo"]


class QuarantineInfo(BaseModel):
    """Why a scene stopped being replicated: attributed deaths, when, and any error.

    This is the wire read shape, independent of the Hub's stored evidence.
    """

    model_config = ConfigDict(frozen=True)

    status: Literal["quarantined"] = "quarantined"
    death_count: int
    last_death_at: float
    # Populated only when the Display managed to report a render error before
    # dying; absence means none was ever received, not that none occurred.
    render_error: str | None = None
