"""Outbound wire message delivered to a connection's topic subscribers."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

__all__ = [
    "ObserverMessage",
    "register_codecs",
]


@dataclass(frozen=True, slots=True)
class ObserverMessage:
    """Outbound delivery for a publish on a topic the connection subscribed to.

    The Hub constructs this when ``Hub.publish`` fans a payload out to
    one of its connection-scoped topics. Each subscriber's writer
    receives the typed value; serialization to the wire happens at the
    transport boundary via the message registry. Agents never construct
    this message directly — it appears only on the outbound side of a
    connection that has subscribed to a topic and another call on that
    connection has published to it.
    """

    topic: str
    payload: Mapping[str, Any]
    type: Literal["observer"] = "observer"


def _observer_to_dict(msg: ObserverMessage) -> dict[str, Any]:
    return {
        "type": msg.type,
        "topic": msg.topic,
        "payload": dict(msg.payload),
    }


def _observer_from_dict(d: dict[str, Any]) -> ObserverMessage:
    raw_payload = d.get("payload", {})
    payload: dict[str, Any] = (
        cast("dict[str, Any]", raw_payload) if isinstance(raw_payload, dict) else {}
    )
    return ObserverMessage(topic=d["topic"], payload=payload)


_Register = Callable[
    [str, type, Callable[..., dict[str, Any]], Callable[[dict[str, Any]], Any]],
    None,
]


def register_codecs(register: _Register) -> None:
    """Register this module's message codecs into a MessageRegistry."""
    register("observer", ObserverMessage, _observer_to_dict, _observer_from_dict)
