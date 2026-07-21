"""The acknowledgement results for subscribe, unsubscribe, and publish."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

__all__ = ["Published", "Subscribed", "Unsubscribed"]


class Subscribed(BaseModel):
    """The caller's session is now registered for ``topic``."""

    kind: Literal["ok"] = "ok"
    topic: str


class Unsubscribed(BaseModel):
    """The caller's session no longer holds a subscription to ``topic``."""

    kind: Literal["ok"] = "ok"
    topic: str


class Published(BaseModel):
    """A publish fanned out to ``delivered`` in-scope subscribers."""

    kind: Literal["ok"] = "ok"
    delivered: int
