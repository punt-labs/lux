"""The publish request and the received-event result for app pub-sub."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

__all__ = ["BusEvent", "PublishRequest", "Received"]


class BusEvent(BaseModel):
    """One business event on a topic the caller's session subscribed to."""

    topic: str
    # App-defined topic payload; no fixed schema (PY-TS-14 wire boundary).
    payload: dict[str, object]


class Received(BaseModel):
    """The next queued business event, or nothing when the inbox is empty."""

    kind: Literal["ok"] = "ok"
    event: BusEvent | None = None  # None is the documented "inbox empty" contract


class PublishRequest(BaseModel):
    """The payload to fan out to a topic's subscribers."""

    # App-defined topic payload; no fixed schema (PY-TS-14 wire boundary).
    payload: dict[str, object] = Field(default_factory=dict)
