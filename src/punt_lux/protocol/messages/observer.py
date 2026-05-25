"""Outbound wire message delivered to a connection's topic subscribers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal, Self, cast

__all__ = ["ObserverMessage", "register_codecs"]


@dataclass(frozen=True, slots=True)
class ObserverMessage:
    """Outbound delivery for a publish on a topic the connection subscribed to.

    The Hub constructs this when ``Hub.publish`` fans a payload out to one of
    its connection-scoped topics. Each subscriber's writer receives the typed
    value; serialization to the wire happens at the transport boundary via the
    message registry. Agents never construct this directly — it appears only on
    the outbound side of a connection that subscribed to a topic and another
    call on that connection published to it.
    """

    topic: str
    # open-ended agent payload; no fixed schema — `object` keeps the wire
    # boundary honest (PY-TS-14) instead of laundering it as ``Any``.
    payload: Mapping[str, object]
    type: Literal["observer"] = "observer"

    def to_dict(self) -> dict[str, object]:
        """Return the wire representation of this message."""
        return {"type": self.type, "topic": self.topic, "payload": dict(self.payload)}

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        """Build an ``ObserverMessage`` from its wire representation."""
        topic = d.get("topic")
        if not isinstance(topic, str):
            msg = f"ObserverMessage.topic must be str, got {type(topic).__name__}"
            raise ValueError(msg)
        payload = d.get("payload", {})
        if not isinstance(payload, Mapping):
            kind = type(payload).__name__
            msg = f"ObserverMessage.payload must be Mapping, got {kind}"
            raise ValueError(msg)
        return cls(topic=topic, payload=dict(cast("Mapping[str, object]", payload)))


_ToDict = Callable[..., dict[str, object]]
_FromDict = Callable[[dict[str, object]], object]
_Register = Callable[[str, type, _ToDict, _FromDict], None]


def register_codecs(register: _Register) -> None:
    """Register this module's message codecs into a MessageRegistry."""
    register(
        "observer",
        ObserverMessage,
        ObserverMessage.to_dict,
        ObserverMessage.from_dict,
    )
