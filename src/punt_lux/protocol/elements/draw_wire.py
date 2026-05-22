"""``WireContext`` — decode-time context for typed wire dicts.

One context per dict; the prefix (``draw command [3] (circle)`` or
``progress element``) is computed at construction and reused in every
error message.  Methods validate primitive types and raise ``ValueError``
on malformed input — no method returns ``None`` on bad input.

Factory classmethods: ``at_index`` (draw-decoder predispatch),
``for_indexed`` (per-command), ``for_element`` (basics ``from_dict``).
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

    @classmethod
    def for_element(cls, kind: str) -> Self:
        """Element-family context: prefix is ``{kind} element``."""
        return cls(_prefix=f"{kind} element")

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

    def optional_string(
        self, d: Mapping[str, object], field: str, *, default: str
    ) -> str:
        """Return ``d[field]`` as str, ``default`` if absent; raise on wrong type."""
        if field not in d:
            return default
        return self.require_string(d[field], field)

    def optional_number(
        self, d: Mapping[str, object], field: str, *, default: float
    ) -> float:
        """Return ``d[field]`` as float, ``default`` if absent; raise on wrong type."""
        if field not in d:
            return default
        return self.require_number(d[field], field)

    def optional_int(
        self, d: Mapping[str, object], field: str, *, default: int | None = None
    ) -> int | None:
        """Return ``d[field]`` as int, ``default`` if absent; raise on wrong type."""
        if field not in d:
            return default
        raw = d[field]
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise self.field_error(field, "an int", raw)
        return raw

    def optional_nullable_string(
        self, d: Mapping[str, object], field: str
    ) -> str | None:
        """Return ``d[field]`` as str, ``None`` if absent; raise on wrong type."""
        if field not in d:
            return None
        return self.require_string(d[field], field)

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
