"""ClientList — the Hub session registry, the meaningful client answer.

After the Hub took over, the display has exactly one socket client: luxd. The
meaningful client list is the set of Hub sessions — the connections and their
scopes — which the Hub already holds.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = ["ClientList", "HubClient"]


class HubClient(BaseModel):
    """One Hub session: its connection, age, subscriptions, and owned scenes."""

    model_config = ConfigDict(frozen=True)

    connection_id: str
    connected_seconds: float
    subscribed_topics: list[str]
    owned_scenes: list[str]


class ClientList(BaseModel):
    """Every connection the Hub currently holds a session for."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
    clients: list[HubClient]
