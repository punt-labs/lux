"""Display process identity, with a Hub dial name only for Hub-proxied facts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Self

from pydantic import BaseModel, Field, ValidationError

from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.hub_connection import HubConnection


class DisplayIdentity(BaseModel, frozen=True):
    """The process lifetime is distinct from any connection the Hub makes to it."""

    pid: int
    uptime_seconds: float
    protocol_version: str
    hub_connection_id: HubConnection = Field(default_factory=HubConnection)

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> Self | OpError:
        """Validate facts in the concrete shape, preserving malformed-reply errors."""
        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            return OpError.from_reply(exc)
