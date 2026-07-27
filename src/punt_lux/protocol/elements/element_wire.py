"""``ElementWireContext`` — wire-decode context for ``Element.from_dict`` codecs.

Sibling of ``WireContext`` (draw-command decoding).  Carries the element
kind in its prefix (``{kind} element``) and adds the optional-field helpers
the codecs need: ``optional_str``, ``optional_number``, ``optional_int``,
``optional_bool``, ``optional_nullable_str``.  Required-field validation
delegates to the wrapped ``WireContext``.

The split exists because draw-command decoding and element decoding have
different responsibilities (PY-IC-6 / SRP).  Sharing the primitive
validators via composition keeps the wire-validation vocabulary in one
class while letting each surface own its boundary semantics.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Self, cast

from punt_lux.protocol.elements.draw_wire import WireContext

__all__ = ["ElementWireContext"]


@dataclass(frozen=True, slots=True)
class ElementWireContext:
    """Per-element decode context — prefix is ``{kind} element``."""

    _wire: WireContext
    _kind: str

    @classmethod
    def for_kind(cls, kind: str) -> Self:
        """Build a context for decoding an element of the given wire kind."""
        return cls(_wire=WireContext(_prefix=f"{kind} element"), _kind=kind)

    def decode_children[T](
        self,
        container_id: str,
        items: Iterable[object],
        decode: Callable[[object], T],
    ) -> tuple[T, ...]:
        """Decode each contained item, naming this container and slot on a failure.

        A malformed child raises deep in the recursion — a bad value or unknown
        kind (``ValueError``) or a wrong-typed wire shape such as a non-mapping
        child or a non-list ``children`` (``TypeError``). Both are re-raised as
        their own class, prefixed with this container's kind, id, and the child
        index, so the failure keeps its value/shape distinction and traces to the
        exact slot of the composite that carried it, not just to the offending
        leaf.
        """
        decoded: list[T] = []
        for index, item in enumerate(items):
            try:
                decoded.append(decode(item))
            except (ValueError, TypeError) as exc:
                prefixed = f"{self._kind} {container_id!r} child {index}: {exc}"
                raise type(exc)(prefixed) from exc
        return tuple(decoded)

    # --- required-field passthroughs to WireContext -----------------------

    def require_str(self, d: Mapping[str, object], field: str) -> str:
        """Return ``d[field]`` as str; raise on missing or wrong type."""
        return self._wire.require_string(self._wire.require_field(d, field), field)

    def require_id(self, d: Mapping[str, object], field: str = "id") -> str:
        """Return ``d[field]`` as a NON-empty str; raise on missing/empty/wrong type.

        A non-anonymous element must carry a real identity. An empty ``id``
        passes ``require_str`` but then collides in the Hub store and crashes
        the dual-write pump's anonymous-id synthesis — a path only the
        ``Anonymizable`` ``separator`` (which decodes its id with ``optional_str``)
        may reach. Every other kind rejects an empty id here, at the boundary.
        """
        value = self.require_str(d, field)
        if not value:
            raise self._wire.field_error(field, "a non-empty string", value)
        return value

    def require_number(self, d: Mapping[str, object], field: str) -> float:
        """Return ``d[field]`` as float; raise on missing, bool, or wrong type."""
        return self._wire.require_number(self._wire.require_field(d, field), field)

    # --- optional-with-default helpers ------------------------------------

    def optional_str(self, d: Mapping[str, object], field: str, *, default: str) -> str:
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

    def optional_bool(
        self, d: Mapping[str, object], field: str, *, default: bool
    ) -> bool:
        """Return ``d[field]`` as bool, ``default`` if absent; raise on wrong type."""
        if field not in d:
            return default
        raw = d[field]
        if not isinstance(raw, bool):
            raise self._wire.field_error(field, "bool", raw)
        return raw

    def optional_int(self, d: Mapping[str, object], field: str) -> int | None:
        """Return ``d[field]`` as int, ``None`` if absent or explicitly null.

        A wire payload that carries ``{"width": null}`` is treated the
        same as one that omits ``width`` — both yield ``None``.  Only
        present, non-None, non-int values raise.
        """
        if field not in d:
            return None
        raw = d[field]
        if raw is None:
            return None
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise self._wire.field_error(field, "an int", raw)
        return raw

    def optional_string_list(self, d: Mapping[str, object], field: str) -> list[str]:
        """Return ``d[field]`` as ``list[str]``; empty list if absent.

        PY-EH-1: every element of a present list is type-checked; a
        non-string element raises with the offending index in the message.
        """
        if field not in d:
            return []
        raw = d[field]
        if not isinstance(raw, list):
            raise self._wire.field_error(field, "a list", raw)
        seq = cast("list[object]", raw)
        for i, item in enumerate(seq):
            if not isinstance(item, str):
                indexed = f"{field}[{i}]"
                raise self._wire.field_error(indexed, "a string", item)
        return cast("list[str]", list(seq))

    def optional_int_with_default(
        self, d: Mapping[str, object], field: str, *, default: int
    ) -> int:
        """Return ``d[field]`` as int, ``default`` if absent; raise on wrong type.

        Distinct from ``optional_int`` which returns ``int | None``: this
        helper is the right tool when ``int`` is total — the caller has a
        meaningful default, and a present null is a wire error.
        """
        if field not in d:
            return default
        raw = d[field]
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise self._wire.field_error(field, "an int", raw)
        return raw

    def optional_nullable_number(
        self, d: Mapping[str, object], field: str
    ) -> float | None:
        """Return ``d[field]`` as float, ``None`` if absent or explicitly null.

        Mirrors ``optional_nullable_str`` / ``optional_int``: explicit ``null``
        and a missing key are the same — both yield ``None``.  Only present
        non-None, non-numeric values raise.
        """
        if field not in d:
            return None
        raw = d[field]
        if raw is None:
            return None
        return self._wire.require_number(raw, field)

    def optional_nullable_str(self, d: Mapping[str, object], field: str) -> str | None:
        """Return ``d[field]`` as str, ``None`` if absent or explicitly null.

        A wire payload that carries ``{"style": null}`` is treated the
        same as one that omits ``style`` — both yield ``None``.  Only
        present, non-None, non-str values raise.
        """
        if field not in d:
            return None
        raw = d[field]
        if raw is None:
            return None
        return self._wire.require_string(raw, field)
