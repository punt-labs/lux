"""WireField — one named place in a replicated payload, and how it is read.

A menu arrives from the Hub as untyped JSON; every reader here returns the
value at its promised type or raises naming the place, so a bad payload
points at ``callback_menus.0.items.2.id`` instead of a bare ``TypeError``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Self, cast, final

__all__ = ["WireField"]


@final
class WireField:
    """The name of one place in a payload, and the readers that check it."""

    _loc: str
    __slots__ = ("_loc",)

    def __new__(cls, loc: str) -> Self:
        self = super().__new__(cls)
        self._loc = loc
        return self

    @property
    def loc(self) -> str:
        """Return the dotted name of this place, as a rejection reports it."""
        return self._loc

    def at(self, part: str | int) -> WireField:
        """Return the field one step further in: the ``items`` of ``menus.0``."""
        return WireField(f"{self._loc}.{part}")

    def mapping(self, value: object) -> Mapping[str, object]:
        """Return *value* as a mapping, or reject it by name."""
        if not isinstance(value, Mapping):
            raise self.rejected("a mapping", value)
        return cast("Mapping[str, object]", value)

    def sequence(self, value: object) -> tuple[object, ...]:
        """Return *value* as a tuple, or reject it (a string here is scalar)."""
        if isinstance(value, str) or not isinstance(value, Sequence):
            raise self.rejected("a list", value)
        return tuple(cast("Sequence[object]", value))

    def text(self, value: object) -> str:
        """Return *value* as a non-empty string, or reject it by name."""
        if not isinstance(value, str) or not value:
            raise self.rejected("a non-empty string", value)
        return value

    def optional_text(self, value: object, default: str) -> str:
        """Return a present string, or *default* when absent; wrong type is rejected."""
        if value is None:
            return default
        if not isinstance(value, str):
            raise self.rejected("a string", value)
        return value

    def optional_text_or_none(self, value: object) -> str | None:
        """Present non-blank string, or None if absent (mirrors the Hub blank rule)."""
        return None if value is None else self._nonblank_text(value)

    def _nonblank_text(self, value: object) -> str:
        """Return *value* as a non-blank string, or reject it by name."""
        if isinstance(value, str) and value.strip():
            return value
        raise ValueError(f"{self._loc}: expected a non-blank string, got {value!r}")

    def flag(self, value: object, *, default: bool) -> bool:
        """Return a present boolean, or *default* when the field is absent."""
        if value is None:
            return default
        if not isinstance(value, bool):
            raise self.rejected("true or false", value)
        return value

    def rejected(self, expected: str, value: object) -> ValueError:
        """Return the error that names this place, what it wanted, and what came."""
        return ValueError(f"{self._loc}: expected {expected}, got {value!r}")
