"""ConnectMessage — a connection's declared identity, Hub identity included."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Self

__all__ = ["ConnectMessage"]

_Register = Callable[
    [str, type, Callable[..., dict[str, Any]], Callable[[dict[str, Any]], Any]],
    None,
]


@dataclass(frozen=True, slots=True)
class ConnectMessage:
    """Client identifies itself to the display server.

    Sent after receiving ``ReadyMessage``.  The *name* field is used for
    display attribution (e.g. frame titles, menu namespaces).  Sending
    again updates the name (idempotent).  ``hub_id`` is a separate concern:
    this connection's own ``HubId.wire_token``.  Every connecting kind
    populates it, including ``"test"`` — a test connection is a same-host-
    only stand-in for a Hub on the ``AF_UNIX`` leg and carries a stub
    ``HubId``, never an absence of one.

    ``kind`` is required, with no default — every caller must declare it
    explicitly.  ``"hub"`` is the one legitimate production writer: luxd's
    ``ClientRegistry``, whose identify triggers single-owner preemption and
    expects a ``HubManifestMessage`` immediately after (DES-068). ``"test"``
    is a deliberately-named test-only backdoor for inspecting a running
    Display without a Hub in the loop — the name reads as wrong at a
    production call site on purpose. A ``"test"`` connection may query and
    observe; a ``SceneMessage`` from one is rejected, not installed (a lux
    client never talks to the Display directly, per target.md).  The
    cross-host listener never accepts ``kind="test"``.
    """

    name: str
    kind: Literal["hub", "test"]
    hub_id: str
    type: Literal["connect"] = "connect"

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the wire dict."""
        return {
            "type": self.type,
            "name": self.name,
            "kind": self.kind,
            "hub_id": self.hub_id,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """Rebuild from a wire dict.

        Raises on a missing/blank name, a missing/blank hub_id, or a bad kind.
        """
        return cls(
            name=cls._require_nonblank_str(d, "name"),
            kind=cls._require_kind(d),
            hub_id=cls._require_nonblank_str(d, "hub_id"),
        )

    @staticmethod
    def _require_nonblank_str(d: dict[str, Any], field: str) -> str:
        """Return ``d[field]`` as a non-blank string, or raise ``ValueError``.

        Shared by every ``ConnectMessage`` string field with the identical
        contract -- present, and not merely whitespace.
        """
        value = d.get(field)
        if not isinstance(value, str) or not value.strip():
            err = f"ConnectMessage missing or invalid {field!r} field"
            raise ValueError(err)
        return value

    @staticmethod
    def _require_kind(d: dict[str, Any]) -> Literal["hub", "test"]:
        kind = d.get("kind")
        if kind == "hub":
            return "hub"
        if kind == "test":
            return "test"
        err = f"ConnectMessage missing or invalid 'kind' field: {kind!r}"
        raise ValueError(err)

    @staticmethod
    def register_codecs(register: _Register) -> None:
        """Register the connect codec into a MessageRegistry."""
        register(
            "connect", ConnectMessage, ConnectMessage.to_dict, ConnectMessage.from_dict
        )
