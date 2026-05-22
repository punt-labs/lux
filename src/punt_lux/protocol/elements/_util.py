"""Small wire-codec utilities shared across element modules."""

from __future__ import annotations

from typing import Any

__all__ = ["strip_none"]


def strip_none(d: dict[str, Any]) -> dict[str, Any]:
    """Return ``d`` with keys whose value is ``None`` removed."""
    return {k: v for k, v in d.items() if v is not None}
