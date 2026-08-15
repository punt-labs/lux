"""Connection-lifecycle messages — ready, connect, hub manifest, ack, ping/pong."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Self

from punt_lux.protocol.messages.unknown_message import UnknownMessage

__all__ = [
    "PROTOCOL_VERSION",
    "AckMessage",
    "ConnectMessage",
    "HubManifestMessage",
    "PingMessage",
    "PongMessage",
    "ReadyMessage",
    "UnknownMessage",
    "register_codecs",
]


PROTOCOL_VERSION = "0.1"

_Register = Callable[
    [str, type, Callable[..., dict[str, Any]], Callable[[dict[str, Any]], Any]],
    None,
]


@dataclass(frozen=True, slots=True)
class PingMessage:
    """Heartbeat / latency probe."""

    type: Literal["ping"] = "ping"
    ts: float | None = None  # absent when the sender omits a timestamp

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the wire dict, omitting an absent timestamp."""
        d: dict[str, Any] = {"type": self.type}
        if self.ts is not None:
            d["ts"] = self.ts
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """Rebuild from a wire dict."""
        return cls(ts=d.get("ts"))


@dataclass(frozen=True, slots=True)
class ConnectMessage:
    """Client identifies itself to the display server.

    Sent after receiving ``ReadyMessage``.  The *name* field is used for
    display attribution (e.g. frame titles, menu namespaces).  Sending
    again updates the name (idempotent).

    ``kind`` distinguishes the Hub's own declared identity (``"hub"``) from
    every other identify (``"direct"`` — CLI probes, tests, and any future
    non-Hub caller).  A ``kind="hub"`` identify triggers single-owner
    preemption and expects a ``HubManifestMessage`` immediately after, so the
    default of ``"direct"`` preserves every existing caller's behavior
    exactly (DES-068).
    """

    name: str
    type: Literal["connect"] = "connect"
    kind: Literal["hub", "direct"] = "direct"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the wire dict."""
        return {"type": self.type, "name": self.name, "kind": self.kind}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """Rebuild from a wire dict; raise on a missing/blank name or bad kind."""
        return cls(name=cls._require_name(d), kind=cls._require_kind(d))

    @staticmethod
    def _require_name(d: dict[str, Any]) -> str:
        name = d.get("name")
        if not isinstance(name, str) or not name.strip():
            err = "ConnectMessage missing or invalid 'name' field"
            raise ValueError(err)
        return name

    @staticmethod
    def _require_kind(d: dict[str, Any]) -> Literal["hub", "direct"]:
        kind = d.get("kind", "direct")
        if kind == "hub":
            return "hub"
        if kind == "direct":
            return "direct"
        err = f"ConnectMessage invalid 'kind' field: {kind!r}"
        raise ValueError(err)


@dataclass(frozen=True, slots=True)
class HubManifestMessage:
    """The declaring Hub's complete, authoritative set of live scene ids.

    Sent by a ``kind="hub"`` connection immediately after ``ConnectMessage``
    and before any ``SceneMessage``.  Empty on a fresh Hub-process restart;
    the full live set on an ordinary reconnect.  On receipt, the display
    purges every scene not named here AND not owned by the identifying fd —
    orphaned scenes from a prior Hub die (owner reassigned to the orphan
    sentinel) are swept by the same rule (DES-068).
    """

    scene_ids: tuple[str, ...]
    type: Literal["hub_manifest"] = "hub_manifest"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the wire dict."""
        return {"type": self.type, "scene_ids": list(self.scene_ids)}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """Rebuild from a wire dict; an absent ``scene_ids`` decodes to empty."""
        return cls(scene_ids=tuple(d.get("scene_ids", [])))


@dataclass(frozen=True, slots=True)
class ReadyMessage:
    """Display is initialized and ready to render."""

    version: str = PROTOCOL_VERSION
    type: Literal["ready"] = "ready"
    capabilities: list[str] = field(default_factory=lambda: list[str]())

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the wire dict, omitting empty capabilities."""
        d: dict[str, Any] = {"type": self.type, "version": self.version}
        if self.capabilities:
            d["capabilities"] = self.capabilities
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """Rebuild from a wire dict."""
        return cls(
            version=d.get("version", PROTOCOL_VERSION),
            capabilities=d.get("capabilities", []),
        )


@dataclass(frozen=True, slots=True)
class AckMessage:
    """Acknowledges a scene or update."""

    scene_id: str
    type: Literal["ack"] = "ack"
    ts: float | None = None  # absent when the sender omits a timestamp
    error: str | None = None  # absent on success; the failure reason otherwise

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the wire dict, omitting absent optional fields."""
        d: dict[str, Any] = {"type": self.type, "scene_id": self.scene_id}
        if self.ts is not None:
            d["ts"] = self.ts
        if self.error is not None:
            d["error"] = self.error
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """Rebuild from a wire dict."""
        return cls(scene_id=d["scene_id"], ts=d.get("ts"), error=d.get("error"))


@dataclass(frozen=True, slots=True)
class PongMessage:
    """Response to a ping."""

    type: Literal["pong"] = "pong"
    ts: float | None = None  # echoes the ping's timestamp, absent if it had none
    display_ts: float | None = None  # absent when the display omits its own clock

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the wire dict, omitting absent optional fields."""
        d: dict[str, Any] = {"type": self.type}
        if self.ts is not None:
            d["ts"] = self.ts
        if self.display_ts is not None:
            d["display_ts"] = self.display_ts
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """Rebuild from a wire dict."""
        return cls(ts=d.get("ts"), display_ts=d.get("display_ts"))


def register_codecs(register: _Register) -> None:
    """Register this module's message codecs into a MessageRegistry."""
    register("ready", ReadyMessage, ReadyMessage.to_dict, ReadyMessage.from_dict)
    register("ack", AckMessage, AckMessage.to_dict, AckMessage.from_dict)
    register("pong", PongMessage, PongMessage.to_dict, PongMessage.from_dict)
    register("ping", PingMessage, PingMessage.to_dict, PingMessage.from_dict)
    register(
        "connect", ConnectMessage, ConnectMessage.to_dict, ConnectMessage.from_dict
    )
    register(
        "hub_manifest",
        HubManifestMessage,
        HubManifestMessage.to_dict,
        HubManifestMessage.from_dict,
    )
    register(
        "unknown", UnknownMessage, UnknownMessage.to_dict, UnknownMessage.from_dict
    )
