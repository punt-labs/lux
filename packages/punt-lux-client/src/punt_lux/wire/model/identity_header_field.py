"""IdentityHeaderField -- one identity field and the one header it travels in."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, final

from punt_lux.wire.model.header_value import HeaderValue

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.wire.model.client_identity import ClientIdentity

__all__ = ["IdentityHeaderField"]


@final
class IdentityHeaderField:
    """Know an identity field's header, how it renders there and how it reads back.

    One declaration covers both wire directions, so a field cannot be written one
    way and read another. A blank header equals no header: an absent value renders
    as ``""`` and a missing or blank header reads back as ``""``.
    """

    _name: str
    _header: str
    _is_encoded: bool
    __slots__ = ("_header", "_is_encoded", "_name")

    def __new__(cls, name: str, header: str, *, is_encoded: bool = True) -> Self:
        """Declare the identity field ``name`` carried in ``header``.

        ``is_encoded`` percent-encodes a free-text value; a kind or a number
        already crosses as ASCII and is formatted as is.
        """
        self = super().__new__(cls)
        self._name = name
        self._header = header
        self._is_encoded = is_encoded
        return self

    @property
    def name(self) -> str:
        """The identity field this header carries."""
        return self._name

    @property
    def header(self) -> str:
        """The header name."""
        return self._header

    def render(self, identity: ClientIdentity) -> str:
        """Return the header text ``identity`` gives this field; ``""`` if absent."""
        value = getattr(identity, self._name)
        if value is None:
            return ""
        return HeaderValue.sent(value) if self._is_encoded else str(value)

    def read(self, headers: Mapping[str, str]) -> str:
        """Return the text a request declared for this field; ``""`` if none."""
        return HeaderValue.declared(headers.get(self._header, ""))
