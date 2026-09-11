"""Hostname -- an ASCII network hostname, canonical (lowercase) once built.

Owns exactly one invariant, in its own construction: a hostname is either
ASCII and gets lowercased, or it is rejected outright. Composed into
:class:`~punt_lux.domain.hub_id.HubId` (DES-090 W9) so that every
construction path -- ``HubId.current()``, ``HubId.stub()``, a cross-host
peer's self-reported ``hub_id`` resolved off the wire -- agrees on the same
identity for the same host, illegal (non-ASCII, mixed-case-as-distinct)
states never representable in the first place.
"""

from __future__ import annotations

from typing import Self, final

__all__ = ["Hostname"]


@final
class Hostname:
    """An ASCII hostname, always lowercase once constructed.

    FQDNs are ASCII, or punycode (RFC 3492) for a non-ASCII domain -- never
    raw Unicode. DNS names are case-insensitive (RFC 4343), and a plain
    ASCII ``str.lower()`` is exact and total *because* the input is
    ASCII-only: Unicode-aware folding (``str.casefold()``) is what would be
    needed for non-ASCII input, and casefold collides distinct strings
    (``"faß"`` and ``"fass"`` casefold identically) -- exactly the kind of
    identity collision this class exists to close. Rejecting non-ASCII
    outright removes the need for that collision-prone fold rather than
    trading one masquerade risk for another.
    """

    _value: str
    __slots__ = ("_value",)

    def __new__(cls, value: str) -> Self:
        if not value.isascii():
            msg = f"Hostname must be ASCII (FQDNs are ASCII/punycode): {value!r}"
            raise ValueError(msg)
        self = super().__new__(cls)
        self._value = value.lower()
        return self

    @property
    def value(self) -> str:
        """The canonical (ASCII-lowercase) hostname string."""
        return self._value

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Hostname):
            return NotImplemented
        return self._value == other._value

    def __hash__(self) -> int:
        return hash((Hostname, self._value))

    def __repr__(self) -> str:
        return f"Hostname({self._value!r})"
