"""Display process identity, with a Hub dial name only for Hub-proxied facts."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Self, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_serializer,
    model_validator,
)

from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.hub_connected import HubConnected
from punt_lux.operations.models.hub_unobserved import HubUnobserved

type HubConnection = Annotated[
    HubConnected | HubUnobserved, Field(discriminator="state")
]


class DisplayIdentity(BaseModel, frozen=True):
    """The process lifetime is distinct from any connection the Hub makes to it."""

    pid: int
    uptime_seconds: float
    protocol_version: str
    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)
    hub_connection: HubConnection = Field(
        default_factory=HubUnobserved, alias="hub_connection_id"
    )

    @property
    def hub_connection_id(self) -> str | None:
        """Expose the wire name while retaining a discriminated connection state."""
        if isinstance(self.hub_connection, HubConnected):
            return self.hub_connection.name
        return None

    @field_serializer("hub_connection")
    def _serialize_connection(self, value: HubConnection) -> str | None:
        return value.name if isinstance(value, HubConnected) else None

    @model_validator(mode="before")
    @classmethod
    def _connection_state(cls, value: object) -> object:
        if not isinstance(value, Mapping):
            return value
        payload = dict(cast("Mapping[str, object]", value))
        if (
            (name := payload.pop("hub_connection_id", None)) is not None
            and name != ""
            and "hub_connection" not in payload
        ):
            payload["hub_connection"] = {"state": "connected", "name": name}
        return payload

    @classmethod
    def from_payload(cls, payload: Mapping[str, object]) -> Self | OpError:
        """Validate facts in the concrete shape, preserving malformed-reply errors."""
        try:
            return cls.model_validate(payload)
        except ValidationError as exc:
            return OpError.from_reply(exc)
