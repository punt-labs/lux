"""Closed session-state vocabulary for the daemon's authoritative parser."""

from __future__ import annotations

from enum import StrEnum


class SessionState(StrEnum):
    RUNNING = "running"
    EXITED = "exited"
    FAILED = "failed"
    CLOSED = "closed"
