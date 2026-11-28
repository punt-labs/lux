"""The service operations' result models (DES-107)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

__all__ = ["RelayReply", "ServiceEntry", "ServiceList"]


class ServiceEntry(BaseModel):
    """One registration: a service, and the host whose client serves it."""

    model_config = ConfigDict(frozen=True)

    service: str
    host: str


class ServiceList(BaseModel):
    """Every registration, ordered by service then host."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
    services: list[ServiceEntry]


class RelayReply(BaseModel):
    """The provider's reply payload."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["ok"] = "ok"
    payload: dict[str, object]
