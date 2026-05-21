"""``WireContext`` — decode-time context for draw-command wire dicts.

Every draw command wire dict is decoded inside one ``WireContext``.  It
carries the command kind and its position in the parent list so every
field error reports a uniform ``draw command [i] (kind)`` prefix.  Its
methods raise the project-style ``ValueError`` and validate primitive
types (bool, string, presence) — the typed value classes
(``Point2``, ``Color``, ``Thickness``, ``Radius``, ``Rounding``) call
back into the context for error formatting.

Two pure helpers live alongside the class: ``coerce_number`` (accepts
``int``/``float``, rejects ``bool``) and ``object_sequence`` (narrows a
list/tuple to a tuple of ``object``).  They have no context state and
stay as module-level functions.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

__all__ = [
    "WireContext",
    "coerce_number",
    "object_sequence",
]


def coerce_number(raw: object) -> float | None:
    """Return ``raw`` as a ``float`` if it is a non-bool number, else ``None``."""
    if isinstance(raw, bool) or not isinstance(raw, int | float):
        return None
    return float(raw)


def object_sequence(raw: object) -> tuple[object, ...] | None:
    """Return ``raw`` as a tuple of ``object`` if it's a list/tuple, else None."""
    if not isinstance(raw, list | tuple):
        return None
    # isinstance narrowing widens raw to list[Unknown]/tuple[Unknown,...].
    # ``cast`` re-asserts the public element type — values come from JSON
    # and are ``object`` until the caller narrows further with isinstance.
    seq = cast("list[object] | tuple[object, ...]", raw)
    return tuple(seq)


@dataclass(frozen=True, slots=True)
class WireContext:
    """Context for decoding one draw-command wire dict.

    Carries the command kind and its position in the parent list so every
    field error reports the same ``draw command [i] (kind)`` prefix.
    """

    kind: str
    index: int | None = None

    @property
    def prefix(self) -> str:
        """Return the leading ``draw command [i] (kind)`` segment of an error."""
        if self.index is None:
            return f"draw command ({self.kind})"
        return f"draw command [{self.index}] ({self.kind})"

    def field_error(
        self,
        field: str,
        expected: str,
        value: object,
    ) -> ValueError:
        """Build a project-style ``ValueError`` for a malformed field."""
        msg = f"{self.prefix} field {field!r} must be {expected}; got {value!r}"
        return ValueError(msg)

    def require_field(self, d: Mapping[str, object], field: str) -> object:
        """Return ``d[field]``; raise ``ValueError`` if missing."""
        if field not in d:
            msg = f"{self.prefix} missing required field {field!r}"
            raise ValueError(msg)
        return d[field]

    def require_bool(self, raw: object, field: str) -> bool:
        """Return ``raw`` as a ``bool`` or raise."""
        if not isinstance(raw, bool):
            raise self.field_error(field, "bool", raw)
        return raw

    def require_string(self, raw: object, field: str) -> str:
        """Return ``raw`` as a ``str`` or raise."""
        if not isinstance(raw, str):
            raise self.field_error(field, "string", raw)
        return raw
