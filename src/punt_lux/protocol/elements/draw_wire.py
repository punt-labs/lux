"""``WireContext`` — decode-time context for draw-command wire dicts.

Every draw command wire dict is decoded inside one ``WireContext``.  The
context carries a single computed prefix string (e.g.
``draw command [3] (circle)``) that every field error reuses.  Its methods
validate primitive types — presence, ``bool``, ``str``, numeric, sequence
— and raise the project-style ``ValueError`` on malformed input.  Every
boundary path is total: a method either returns a typed value or raises.
No method returns ``None`` on bad input.

Construction is via factory classmethods, not by passing ``kind`` /
``index`` separately:

  * :meth:`WireContext.at_index` — predispatch context, used by the
    decoder before the command kind is known.  The prefix is
    ``draw command [{index}]``.
  * :meth:`WireContext.for_indexed` — per-command context, once the
    kind is resolved.  The prefix is
    ``draw command [{index}] ({kind})``.

There is no ``int | None`` anywhere in this module — the discriminated
state of "predispatch" vs "per-command" is collapsed into the prefix
at construction time.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Self, cast

__all__ = ["WireContext"]


@dataclass(frozen=True, slots=True)
class WireContext:
    """Context for decoding one draw-command wire dict.

    Holds the formatted prefix string that every field error reuses.
    Build via the factory classmethods, never by direct construction —
    direct construction is reserved for the factories themselves.
    """

    _prefix: str

    @classmethod
    def at_index(cls, index: int) -> Self:
        """Predispatch context: command kind not yet known.

        Used by the decoder to report errors on the ``cmd`` field
        itself (missing, wrong type, unknown kind).
        """
        return cls(_prefix=f"draw command [{index}]")

    @classmethod
    def for_indexed(cls, kind: str, index: int) -> Self:
        """Per-command context: the kind is resolved.

        Used by every concrete ``DrawCommand.from_wire`` classmethod to format field
        errors with the full ``draw command [i] (kind)`` prefix.
        """
        return cls(_prefix=f"draw command [{index}] ({kind})")

    @property
    def prefix(self) -> str:
        """Return the leading prefix segment of an error message."""
        return self._prefix

    def field_error(
        self,
        field: str,
        expected: str,
        value: object,
    ) -> ValueError:
        """Build a project-style ``ValueError`` for a malformed field."""
        msg = f"{self._prefix} field {field!r} must be {expected}; got {value!r}"
        return ValueError(msg)

    def require_field(self, d: Mapping[str, object], field: str) -> object:
        """Return ``d[field]``; raise ``ValueError`` if missing."""
        if field not in d:
            msg = f"{self._prefix} missing required field {field!r}"
            raise ValueError(msg)
        return d[field]

    def require_bool(self, raw: object, field: str) -> bool:
        """Return ``raw`` as a ``bool`` or raise."""
        if not isinstance(raw, bool):
            raise self.field_error(field, "bool", raw)
        return raw

    def optional_bool(
        self, d: Mapping[str, object], field: str, *, default: bool
    ) -> bool:
        """Return ``d[field]`` as a ``bool``, or ``default`` if absent."""
        if field not in d:
            return default
        return self.require_bool(d[field], field)

    def require_string(self, raw: object, field: str) -> str:
        """Return ``raw`` as a ``str`` or raise."""
        if not isinstance(raw, str):
            raise self.field_error(field, "string", raw)
        return raw

    def require_number(self, raw: object, field: str) -> float:
        """Return ``raw`` as a ``float``, rejecting ``bool`` and non-numerics."""
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            raise self.field_error(field, "a number", raw)
        return float(raw)

    def require_sequence(self, raw: object, field: str) -> tuple[object, ...]:
        """Return ``raw`` as a tuple of ``object`` if it's a list or tuple.

        Raises ``ValueError`` otherwise — callers used to handle ``None``
        themselves; that branch is gone.
        """
        if not isinstance(raw, list | tuple):
            raise self.field_error(field, "a list or tuple", raw)
        # isinstance narrowing widens raw to list[Unknown]/tuple[Unknown,...].
        # cast re-asserts the public element type — values come from JSON
        # and are ``object`` until the caller narrows further with isinstance.
        seq = cast("list[object] | tuple[object, ...]", raw)
        return tuple(seq)
