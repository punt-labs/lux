"""Structured output types for the Lux CLI."""

from __future__ import annotations

from typing import TypedDict


class EnablementReport(TypedDict):
    """Repository activation state and any guide-refresh notice."""

    enabled: bool
    deciding_file: str
    refresh_notice: str | None
