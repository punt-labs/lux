"""Discriminated result of an authoritative Hub write — accepted or rejected.

The ``update`` write path never returns ``T | None`` for "did it apply": a write
either succeeds (:class:`WriteAccepted`) or carries an agent-facing reason it did
not (:class:`WriteRejected`). The tool layer branches on the concrete type rather
than checking a nullable reason string (PY-TS-14 / reduce-``| None``).
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["WriteAccepted", "WriteRejected", "WriteResult"]


@dataclass(frozen=True, slots=True)
class WriteAccepted:
    """The batch was written to the authoritative store; the caller re-pushes."""


@dataclass(frozen=True, slots=True)
class WriteRejected:
    """The batch was refused whole; ``reason`` is the agent-facing explanation.

    The authoritative store is untouched when this is returned — every rejection
    is decided before any live element is committed.
    """

    reason: str


# The two outcomes of an authoritative write. The tool layer matches on the
# concrete type: ``WriteRejected`` yields ``error: scene not updated — <reason>``,
# ``WriteAccepted`` proceeds to the whole-scene re-push.
type WriteResult = WriteAccepted | WriteRejected
