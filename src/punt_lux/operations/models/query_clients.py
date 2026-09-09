"""ClientList and HubClient — the Hub session roster the introspection read returns."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, NonNegativeFloat, NonNegativeInt

from punt_lux.domain.hub.client_identity import ClientIdentity
from punt_lux.domain.hub.lease_term import LeaseTerm

__all__ = ["ClientList", "HubClient"]


class HubClient(BaseModel):
    """One Hub session: connection, identity (None until identified), age, scenes."""

    model_config = ConfigDict(frozen=True)

    connection_id: str
    identity: ClientIdentity | None = None
    connected_seconds: NonNegativeFloat
    lease: LeaseTerm  # the effective lease; a session naming no TTL holds its kind's
    subscribed_topics: list[str]
    owned_scenes: list[str]
    writer_bound: bool  # a Hub.register_writer leg is bound to this connection
    inbox_depth: NonNegativeInt  # queued-but-undelivered events (SimpleQueue.qsize())


class ClientList(BaseModel):
    """Every connection the Hub currently holds a session for."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
    clients: list[HubClient]
