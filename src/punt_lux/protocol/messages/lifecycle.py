"""Connection-lifecycle messages — ready, connect, ack, ping/pong, unknown."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

__all__ = [
    "PROTOCOL_VERSION",
    "AckMessage",
    "ConnectMessage",
    "PingMessage",
    "PongMessage",
    "ReadyMessage",
    "UnknownMessage",
    "register_codecs",
]


PROTOCOL_VERSION = "0.1"


@dataclass(frozen=True, slots=True)
class PingMessage:
    """Heartbeat / latency probe."""

    type: Literal["ping"] = "ping"
    ts: float | None = None


@dataclass(frozen=True, slots=True)
class ConnectMessage:
    """Client identifies itself to the display server.

    Sent after receiving ``ReadyMessage``.  The *name* field is used for
    display attribution (e.g. frame titles, menu namespaces).  Sending
    again updates the name (idempotent).
    """

    name: str
    type: Literal["connect"] = "connect"


@dataclass(frozen=True, slots=True)
class ReadyMessage:
    """Display is initialized and ready to render."""

    version: str = PROTOCOL_VERSION
    type: Literal["ready"] = "ready"
    capabilities: list[str] = field(default_factory=lambda: list[str]())


@dataclass(frozen=True, slots=True)
class AckMessage:
    """Acknowledges a scene or update."""

    scene_id: str
    type: Literal["ack"] = "ack"
    ts: float | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class PongMessage:
    """Response to a ping."""

    type: Literal["pong"] = "pong"
    ts: float | None = None
    display_ts: float | None = None


@dataclass(frozen=True, slots=True)
class UnknownMessage:
    """Passthrough for unrecognized message types.

    Allows forward compatibility: a client sending a message type that
    this version of the display doesn't understand won't be disconnected.
    The display can log and skip unknown messages instead of raising.
    """

    raw_type: str
    data: dict[str, Any] = field(default_factory=lambda: {})  # noqa: PIE807
    type: Literal["unknown"] = "unknown"


def _ts_dict(msg_type: str, ts: float | None) -> dict[str, Any]:
    d: dict[str, Any] = {"type": msg_type}
    if ts is not None:
        d["ts"] = ts
    return d


def _ping_to_dict(m: PingMessage) -> dict[str, Any]:
    return _ts_dict(m.type, m.ts)


def _connect_to_dict(m: ConnectMessage) -> dict[str, Any]:
    return {"type": m.type, "name": m.name}


def _ready_to_dict(m: ReadyMessage) -> dict[str, Any]:
    d: dict[str, Any] = {"type": m.type, "version": m.version}
    if m.capabilities:
        d["capabilities"] = m.capabilities
    return d


def _ack_to_dict(m: AckMessage) -> dict[str, Any]:
    d: dict[str, Any] = {"type": m.type, "scene_id": m.scene_id}
    if m.ts is not None:
        d["ts"] = m.ts
    if m.error is not None:
        d["error"] = m.error
    return d


def _pong_to_dict(m: PongMessage) -> dict[str, Any]:
    d = _ts_dict(m.type, m.ts)
    if m.display_ts is not None:
        d["display_ts"] = m.display_ts
    return d


def _unknown_to_dict(m: UnknownMessage) -> dict[str, Any]:
    d = dict(m.data)
    d["type"] = m.raw_type
    return d


def _ping_from_dict(d: dict[str, Any]) -> PingMessage:
    return PingMessage(ts=d.get("ts"))


def _connect_from_dict(d: dict[str, Any]) -> ConnectMessage:
    name = d.get("name")
    if not isinstance(name, str) or not name.strip():
        err = "ConnectMessage missing or invalid 'name' field"
        raise ValueError(err)
    return ConnectMessage(name=name)


def _ready_from_dict(d: dict[str, Any]) -> ReadyMessage:
    return ReadyMessage(
        version=d.get("version", PROTOCOL_VERSION),
        capabilities=d.get("capabilities", []),
    )


def _ack_from_dict(d: dict[str, Any]) -> AckMessage:
    return AckMessage(scene_id=d["scene_id"], ts=d.get("ts"), error=d.get("error"))


def _pong_from_dict(d: dict[str, Any]) -> PongMessage:
    return PongMessage(ts=d.get("ts"), display_ts=d.get("display_ts"))


def _unknown_from_dict(d: dict[str, Any]) -> UnknownMessage:
    return UnknownMessage(raw_type=d.get("type", "unknown"), data=d)


_Register = Callable[
    [str, type, Callable[..., dict[str, Any]], Callable[[dict[str, Any]], Any]],
    None,
]


def register_codecs(register: _Register) -> None:
    """Register this module's message codecs into a MessageRegistry."""
    register("ready", ReadyMessage, _ready_to_dict, _ready_from_dict)
    register("ack", AckMessage, _ack_to_dict, _ack_from_dict)
    register("pong", PongMessage, _pong_to_dict, _pong_from_dict)
    register("ping", PingMessage, _ping_to_dict, _ping_from_dict)
    register("connect", ConnectMessage, _connect_to_dict, _connect_from_dict)
    register("unknown", UnknownMessage, _unknown_to_dict, _unknown_from_dict)
