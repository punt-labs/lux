"""Scene-replacement messages — full-scene replace and clear.

The two value types. Their wire mapping and its validation live in the sibling
:class:`~punt_lux.protocol.messages.scene_codec.SceneCodec`, to which ``to_dict`` /
``from_dict`` delegate.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Self, cast

from punt_lux.protocol.messages.scene_codec import SceneCodec

if TYPE_CHECKING:
    from punt_lux.protocol.elements import Element

__all__ = [
    "ClearMessage",
    "SceneMessage",
]

_Register = Callable[
    [str, type, Callable[..., dict[str, Any]], Callable[[dict[str, Any]], Any]],
    None,
]


@dataclass(frozen=True, slots=True)
class SceneMessage:
    """Replace the entire display contents, framing the scene it carries."""

    id: str
    elements: list[Element]
    frame_id: str  # required — no scene crosses the wire unframed (Hub self-frames)
    type: Literal["scene"] = "scene"
    layout: Literal["single", "rows", "columns", "grid"] = "single"
    title: str | None = None
    frame_title: str | None = None
    frame_size: tuple[int, int] | None = None
    frame_flags: dict[str, bool] | None = None
    frame_layout: Literal["tab", "stack"] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize to the wire dict (delegates to :class:`SceneCodec`)."""
        return SceneCodec.encode(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """Rebuild from a wire dict (delegates to :class:`SceneCodec`)."""
        return cast("Self", SceneCodec.decode(d))

    @staticmethod
    def register_codecs(register: _Register) -> None:
        """Register the scene and clear codecs into a MessageRegistry."""
        register("scene", SceneMessage, SceneMessage.to_dict, SceneMessage.from_dict)
        register("clear", ClearMessage, ClearMessage.to_dict, ClearMessage.from_dict)


@dataclass(frozen=True, slots=True)
class ClearMessage:
    """Remove all content from the display."""

    type: Literal["clear"] = "clear"

    def to_dict(self) -> dict[str, Any]:
        """Serialize the clear signal to its one-field wire dict."""
        return {"type": self.type}

    @classmethod
    def from_dict(cls, _d: dict[str, Any]) -> Self:
        """Rebuild the clear signal; it carries no wire state."""
        return cls()
