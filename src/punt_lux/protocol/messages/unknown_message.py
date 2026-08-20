"""The registry's universal fallback for any wire type it does not recognize."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Self

__all__ = ["UnknownMessage"]


@dataclass(frozen=True, slots=True)
class UnknownMessage:
    """Passthrough for unrecognized message types.

    Allows forward compatibility: a client sending a message type that
    this version of the display doesn't understand won't be disconnected.
    The display can log and skip unknown messages instead of raising. Every
    message family's ``register_codecs`` funnels its own unrecognized-type
    fallback through this one class — it belongs to no single family.
    """

    raw_type: str
    data: dict[str, Any] = field(default_factory=lambda: {})  # noqa: PIE807
    type: Literal["unknown"] = "unknown"

    def to_dict(self) -> dict[str, Any]:
        """Serialize back to the original wire dict, restoring ``raw_type``."""
        d = dict(self.data)
        d["type"] = self.raw_type
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """Rebuild from a wire dict whose ``type`` matched no registered codec.

        Copies ``d`` rather than storing it by reference: the dataclass is
        frozen, but a dict is mutable regardless of who holds it, so a caller
        mutating the dict it passed in must not reach through to ``data``.
        """
        return cls(raw_type=d.get("type", "unknown"), data=dict(d))
