"""``ElementWireContext`` — wire-decode context for ``Element.from_dict`` codecs.

Sibling of ``WireContext`` (draw-command decoding).  Carries the element
kind in its prefix (``{kind} element``) and adds the four optional helpers
the basics codecs need: ``optional_string``, ``optional_number``,
``optional_int``, ``optional_nullable_string``.  Required-field validation
delegates to the wrapped ``WireContext``.

The split exists because draw-command decoding and element decoding have
different responsibilities (PY-IC-6 / SRP).  Sharing the primitive
validators via composition keeps the wire-validation vocabulary in one
class while letting each surface own its boundary semantics.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Self

from punt_lux.protocol.elements.draw_wire import WireContext

__all__ = ["ElementWireContext"]


@dataclass(frozen=True, slots=True)
class ElementWireContext:
    """Per-element decode context — prefix is ``{kind} element``."""

    _wire: WireContext

    @classmethod
    def for_kind(cls, kind: str) -> Self:
        """Build a context for decoding an element of the given wire kind."""
        return cls(_wire=WireContext(_prefix=f"{kind} element"))

    # --- required-field passthroughs to WireContext -----------------------

    def require_str(self, d: Mapping[str, object], field: str) -> str:
        """Return ``d[field]`` as str; raise on missing or wrong type."""
        return self._wire.require_string(self._wire.require_field(d, field), field)

    def require_number(self, d: Mapping[str, object], field: str) -> float:
        """Return ``d[field]`` as float; raise on missing, bool, or wrong type."""
        return self._wire.require_number(self._wire.require_field(d, field), field)

    # --- optional-with-default helpers ------------------------------------

    def optional_str(
        self, d: Mapping[str, object], field: str, *, default: str
    ) -> str:
        """Return ``d[field]`` as str, ``default`` if absent; raise on wrong type."""
        if field not in d:
            return default
        return self._wire.require_string(d[field], field)

    def optional_number(
        self, d: Mapping[str, object], field: str, *, default: float
    ) -> float:
        """Return ``d[field]`` as float, ``default`` if absent; raise on wrong type."""
        if field not in d:
            return default
        return self._wire.require_number(d[field], field)

    def optional_int(
        self, d: Mapping[str, object], field: str
    ) -> int | None:
        """Return ``d[field]`` as int, ``None`` if absent; raise on wrong type."""
        if field not in d:
            return None
        raw = d[field]
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise self._wire.field_error(field, "an int", raw)
        return raw

    def optional_nullable_str(
        self, d: Mapping[str, object], field: str
    ) -> str | None:
        """Return ``d[field]`` as str, ``None`` if absent; raise on wrong type."""
        if field not in d:
            return None
        return self._wire.require_string(d[field], field)
