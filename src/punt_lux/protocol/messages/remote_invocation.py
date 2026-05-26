"""Serialized handler invocation for remote execution across tiers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

__all__ = [
    "RemoteEventHandlerInvocation",
    "register_codecs",
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


def _invocation_to_dict(msg: RemoteEventHandlerInvocation) -> dict[str, Any]:
    d: dict[str, Any] = {
        "type": msg.type,
        "element_id": msg.element_id,
        "action": msg.action,
    }
    if msg.event_kind is not None:
        d["event_kind"] = msg.event_kind
    if msg.ts is not None:
        d["ts"] = msg.ts
    if msg.value is not None:
        d["value"] = msg.value
    if msg.scene_id is not None:
        d["scene_id"] = msg.scene_id
    return d


def _invocation_from_dict(d: dict[str, Any]) -> RemoteEventHandlerInvocation:
    return RemoteEventHandlerInvocation(
        element_id=d["element_id"],
        action=d["action"],
        event_kind=d.get("event_kind"),
        ts=d.get("ts"),
        value=d.get("value"),
        scene_id=d.get("scene_id"),
    )


_Register = Callable[
    [str, type, Callable[..., dict[str, Any]], Callable[[dict[str, Any]], Any]],
    None,
]


def register_codecs(register: _Register) -> None:
    """Register this module's message codecs into a MessageRegistry."""
    register(
        "remote_invocation",
        RemoteEventHandlerInvocation,
        _invocation_to_dict,
        _invocation_from_dict,
    )
