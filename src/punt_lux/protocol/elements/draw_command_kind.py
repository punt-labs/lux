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
    "WireDict",
]


# PY-TS-14 justification: the JSON-serialised draw-command wire shape is a
# tagged-union whose key set varies per command kind (a circle has "center"
# and "radius"; a triangle has "p1"/"p2"/"p3"; a polyline carries a list of
# coordinate lists).  Each individual command's *concrete* shape is fully
# known via its typed dataclass — but the union at the Protocol level cannot
# be tightened without restating every per-kind schema as a TypedDict alias
# and reimporting it everywhere.  The `dict[str, Any]` here is the
# wire-boundary type, narrowed back to typed values immediately by the
# decoder; downstream code never touches this dict directly.
type WireDict = dict[str, Any]


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

    def to_dict(self) -> WireDict:
        """Serialize this command to its wire dict form."""
        ...
