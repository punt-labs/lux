"""Serialized handler invocation for remote execution across tiers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Self

__all__ = ["RemoteEventHandlerInvocation"]

_Register = Callable[
    [str, type, Callable[..., dict[str, Any]], Callable[[dict[str, Any]], Any]],
    None,
]


@dataclass(frozen=True, slots=True)
class RemoteEventHandlerInvocation:
    """User interacted with an element."""

    element_id: str
    action: str
    event_kind: str | None = None  # identifies the event type (e.g. "button_clicked")
    type: Literal["remote_invocation"] = "remote_invocation"
    ts: float | None = None
    value: Any = None  # wire payload — shape varies by element kind
    scene_id: str | None = None
    # Display-local routing hint for a scene-less (menu) event: the HubId
    # wire_token its menu came from, so delivery names its target fd instead
    # of broadcasting. Never serialized -- absent below, Hub side unread.
    hub_token: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the wire dict; ``hub_token`` never crosses the wire."""
        d: dict[str, Any] = {
            "type": self.type,
            "element_id": self.element_id,
            "action": self.action,
        }
        if self.event_kind is not None:
            d["event_kind"] = self.event_kind
        if self.ts is not None:
            d["ts"] = self.ts
        if self.value is not None:
            d["value"] = self.value
        if self.scene_id is not None:
            d["scene_id"] = self.scene_id
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """Rebuild from a wire dict; ``hub_token`` defaults, never decoded."""
        return cls(
            element_id=d["element_id"],
            action=d["action"],
            event_kind=d.get("event_kind"),
            ts=d.get("ts"),
            value=d.get("value"),
            scene_id=d.get("scene_id"),
        )

    @classmethod
    def register_codecs(cls, register: _Register) -> None:
        """Register this class's codec into a MessageRegistry."""
        register("remote_invocation", cls, cls.to_dict, cls.from_dict)
