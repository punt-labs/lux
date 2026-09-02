"""WireField — one named place in a replicated payload, and how it is read.

A menu arrives from the Hub as untyped JSON, so nothing read out of it is
trusted until it has been checked. A field carries the name of the place being
read — ``callback_menus.0.items.2.id`` — and every reader either returns the
value at the type it promises or raises naming that place, so a rejection says
which field of which menu was wrong instead of leaving a ``TypeError`` to
surface somewhere downstream.
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
        """Return *value* as a tuple, or reject it by name.

        A string is a sequence to Python and a scalar to a reader, so it is
        rejected here rather than iterated one character at a time.
        """
        if isinstance(value, str) or not isinstance(value, Sequence):
            raise self.rejected("a list", value)
        return tuple(cast("Sequence[object]", value))

    def text(self, value: object) -> str:
        """Return *value* as a non-empty string, or reject it by name."""
        if not isinstance(value, str) or not value:
            raise self.rejected("a non-empty string", value)
        return value

    def optional_text(self, value: object, default: str) -> str:
        """Return a present string, or *default* when the field is absent.

        Absence is a documented shape — an item with no accelerator — while a
        present value of the wrong type is a malformed payload and is rejected.
        """
        if value is None:
            return default
        if not isinstance(value, str):
            raise self.rejected("a string", value)
        return value

    def optional_text_or_none(self, value: object) -> str | None:
        """Return a present string, or ``None`` when the field is genuinely absent.

        Unlike :meth:`optional_text`, absence here has no in-band default to
        fall back to -- a genuinely-optional field needs a genuinely-optional
        return type, not a stand-in value.
        """
        if value is None:
            return None
        if not isinstance(value, str):
            raise self.rejected("a string", value)
        return value

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
