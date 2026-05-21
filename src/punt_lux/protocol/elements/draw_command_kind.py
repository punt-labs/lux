"""``DrawCommandKind`` enum and the structural ``DrawCommand`` Protocol.

Every typed draw command carries a ``kind`` attribute typed as a
``Literal[DrawCommandKind.<KIND>]`` and serializes via ``to_dict``. The
``DrawCommand`` Protocol captures that structural shape so callers can
hold any draw command without a base-class hierarchy — concrete command
classes live in sibling ``draw_commands_*`` modules and satisfy this
Protocol implicitly. Decoding is the decoder's responsibility, not the
Protocol's, so the contract stays narrow and testable.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

__all__ = [
    "DrawCommand",
    "DrawCommandKind",
]


class DrawCommandKind(StrEnum):
    """Wire-kind strings recognised by the decoder."""

    LINE = "line"
    RECT = "rect"
    CIRCLE = "circle"
    TRIANGLE = "triangle"
    TEXT = "text"
    POLYLINE = "polyline"
    BEZIER_CUBIC = "bezier_cubic"


@runtime_checkable
class DrawCommand(Protocol):
    """Structural contract every typed draw command satisfies.

    Concrete classes narrow ``kind`` to a single
    ``Literal[DrawCommandKind.<KIND>]`` so the type checker can discriminate
    on it. ``to_dict`` returns the wire form of this one command.
    """

    @property
    def kind(self) -> DrawCommandKind:
        """Wire-kind identifier for this command."""
        ...

    def to_dict(self) -> dict[str, Any]:
        """Serialize this command to its wire dict form."""
        ...
