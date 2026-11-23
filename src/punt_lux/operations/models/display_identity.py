"""Display process identity, with a Hub dial name only for Hub-proxied facts."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from pydantic import BaseModel, ValidationError

from punt_lux.operations.models.common import OpError

if TYPE_CHECKING:
    from collections.abc import Mapping


class DisplayIdentity(BaseModel):
    """The process lifetime is distinct from any connection the Hub makes to it."""

    pid: int
    uptime_seconds: float
    protocol_version: str
    # Raw Display replies have no Hub dial; the Hub attaches its pinned name.
    hub_connection_id: str | None = None

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> Self | OpError:
        """Validate facts in the concrete shape, preserving malformed-reply errors."""
        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            return OpError.from_reply(exc)
