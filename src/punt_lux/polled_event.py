"""Typed envelope surfaced by :meth:`DisplayClient.poll_event`."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

__all__ = ["PolledEvent"]


@dataclass(frozen=True, slots=True)
class PolledEvent:
    """One observer fan-out surfaced to :meth:`DisplayClient.poll_event`.

    Carries both the publisher's ``topic`` and the ``payload`` body so
    subscribers can disambiguate fan-outs from multiple topics on the
    same connection.
    """

    topic: str
    payload: Mapping[str, object]
