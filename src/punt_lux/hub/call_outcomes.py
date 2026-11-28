"""How a relayed call ends: one of four outcomes, or a refused entry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

__all__ = [
    "CallOutcome",
    "Lost",
    "ProviderBusyError",
    "Refused",
    "Replied",
    "TimedOut",
]


@dataclass(frozen=True, slots=True)
class Replied:
    """The provider answered; ``payload`` is its reply."""

    payload: dict[str, object]  # wire boundary; the caller parses it into a model


@dataclass(frozen=True, slots=True)
class Refused:
    """The provider refused, or its reply could not be used."""

    code: Literal["rejected", "invalid_request", "not_found", "fault"]
    reason: str


@dataclass(frozen=True, slots=True)
class TimedOut:
    """The provider did not answer before the deadline."""


@dataclass(frozen=True, slots=True)
class Lost:
    """The provider's session ended before it answered."""


CallOutcome = Replied | Refused | TimedOut | Lost


class ProviderBusyError(Exception):
    """The provider's session already has its limit of calls pending."""
