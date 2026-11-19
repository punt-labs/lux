"""Viewer lifecycle is separate from the daemon's program lifecycle."""

from __future__ import annotations

from enum import StrEnum


class RemotePhase(StrEnum):
    CONNECTING = "connecting"
    SNAPSHOT = "receiving snapshot"
    READY = "ready"
    EXITED = "process exited"
    DISCONNECTED = "disconnected"
    FAILED = "failed"
    CLOSED = "closed"
