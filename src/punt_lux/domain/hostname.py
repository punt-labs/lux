"""Hostname -- an ASCII network hostname, canonical (lowercase) once built.

Owns exactly one invariant, in its own construction: a hostname is either
ASCII and gets lowercased, or it is rejected outright. Composed into
:class:`~punt_lux.domain.hub_id.HubId` so that every construction path --
``HubId.current()``, ``HubId.stub()``, a cross-host peer's self-reported
``hub_id`` resolved off the wire -- agrees on the same identity for the same
host, illegal (non-ASCII, mixed-case-as-distinct) states never representable
in the first place.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import final

__all__ = ["Hostname"]


@final
@dataclass(frozen=True, slots=True)
class Hostname:
    """An ASCII hostname, always lowercase once constructed.

    Frozen so that the hash of a value already used as (or composed into) a
    dict/registry key can never be corrupted by a post-construction write.

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

    value: str

    def __post_init__(self) -> None:
        if not self.value.isascii():
            msg = f"Hostname must be ASCII (FQDNs are ASCII/punycode): {self.value!r}"
            raise ValueError(msg)
        object.__setattr__(self, "value", self.value.lower())
