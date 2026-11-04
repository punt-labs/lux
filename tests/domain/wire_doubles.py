"""Test doubles for the nesting cap: things that are nothing but a wire form."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Mapping


@final
class WireOnly:
    """A wire ``Element`` that is nothing but a wire dict, or one that cannot encode.

    ``encode_error`` makes ``to_dict`` raise it, standing in for a form too deep for
    the encoder to walk.
    """

    _wire: dict[str, object]
    _encode_error: BaseException | None
    __slots__ = ("_encode_error", "_wire")

    def __new__(
        cls,
        wire: dict[str, object],
        encode_error: BaseException | None = None,  # None: it encodes normally
    ) -> Self:
        self = super().__new__(cls)
        self._wire = wire
        self._encode_error = encode_error
        return self

    @property
    def id(self) -> str:
        return str(self._wire.get("id", ""))

    @property
    def kind(self) -> str:
        return str(self._wire.get("kind", "box"))

    @property
    def tooltip(self) -> str | None:
        return None

    def to_dict(self) -> dict[str, object]:
        if self._encode_error is not None:
            raise self._encode_error
        return self._wire

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        return cls(dict(d))
