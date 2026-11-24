"""The Hub's named, pinned connection to a Display."""

from __future__ import annotations

from typing import Annotated, Literal, Self

from pydantic import Field, RootModel, model_serializer, model_validator
from pydantic.dataclasses import dataclass


@dataclass(frozen=True, slots=True, kw_only=True)
class HubConnected:
    """A dial identity names a connection, not the Display process lifetime."""

    state: Literal["connected"] = "connected"
    name: Annotated[str, Field(min_length=1)]


@dataclass(frozen=True, slots=True)
class HubUnobserved:
    """Facts obtained without a Hub-pinned connection."""

    state: Literal["unobserved"] = "unobserved"


type ConnectionState = Annotated[
    HubConnected | HubUnobserved, Field(discriminator="state")
]


class HubConnection(RootModel[ConnectionState], frozen=True):
    """A discriminated connection state with a scalar wire representation."""

    root: ConnectionState = Field(default_factory=HubUnobserved)

    @classmethod
    def observed(cls, name: str) -> Self:
        """Bind a known live dial, rather than optional raw Display facts."""
        return cls(HubConnected(name=name))

    @model_validator(mode="before")
    @classmethod
    def _from_wire(cls, value: object) -> object:
        if value is None or value == "":
            return HubUnobserved()
        if isinstance(value, str):
            return HubConnected(name=value)
        return value

    @property
    def name(self) -> str | None:
        """Return the pinned dial name when a Hub has observed it."""
        return self.root.name if isinstance(self.root, HubConnected) else None

    @model_serializer
    def _to_wire(self) -> str | None:
        return self.name
