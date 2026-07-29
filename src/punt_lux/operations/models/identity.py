"""Identified — the result of a client's ``identify`` first-call."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from punt_lux.domain.hub.client_identity import ClientIdentity

__all__ = ["Identified"]


class Identified(BaseModel):
    """The identity the Hub recorded for the caller, tagged ``ok`` for success."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
    identity: ClientIdentity
