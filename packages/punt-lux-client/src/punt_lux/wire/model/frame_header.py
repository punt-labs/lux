"""Bounds and encoding shared by incremental and blocking wire readers."""

from __future__ import annotations

__all__ = ["HEADER_FORMAT", "HEADER_SIZE", "MAX_MESSAGE_SIZE"]

MAX_MESSAGE_SIZE = 16 * 1024 * 1024
HEADER_SIZE = 4
HEADER_FORMAT = "!I"
