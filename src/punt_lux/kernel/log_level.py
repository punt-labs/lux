"""Resolve Lux's logging level, retaining the legacy applet import."""

from __future__ import annotations

import logging
import os

__all__ = ["level_from_env"]
_LEVELS = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})


def resolve_level(default: str) -> tuple[str, bool]:
    """Resolve the Lux environment override and report whether it was invalid."""
    requested = os.environ.get("LUX_LOG_LEVEL", "").upper()
    if requested in _LEVELS:
        return requested, False
    return default, bool(requested)


def level_from_env(default: str) -> int:
    """Return the level number without configuring any diagnostic sinks."""
    name, _invalid = resolve_level(default)
    return logging.getLevelNamesMapping()[name]
