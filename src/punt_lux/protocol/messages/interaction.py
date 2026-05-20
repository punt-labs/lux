"""User-interaction message — agent event from a user-driven element."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

__all__ = [
    "InteractionMessage",
    "register_codecs",
]


@dataclass(frozen=True, slots=True)
class InteractionMessage:
    """User interacted with an element."""

    element_id: str
    action: str
    type: Literal["interaction"] = "interaction"
    ts: float | None = None
    value: Any = None
    scene_id: str | None = None


def _interaction_to_dict(msg: InteractionMessage) -> dict[str, Any]:
    d: dict[str, Any] = {
        "type": msg.type,
        "element_id": msg.element_id,
        "action": msg.action,
    }
    if msg.ts is not None:
        d["ts"] = msg.ts
    if msg.value is not None:
        d["value"] = msg.value
    if msg.scene_id is not None:
        d["scene_id"] = msg.scene_id
    return d


def _interaction_from_dict(d: dict[str, Any]) -> InteractionMessage:
    return InteractionMessage(
        element_id=d["element_id"],
        action=d["action"],
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
        "interaction", InteractionMessage, _interaction_to_dict, _interaction_from_dict
    )
