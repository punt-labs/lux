"""Decoder + Encoder Protocols for wire codecs.

Wire-side structural contracts. Decoder reads a wire dict and returns an
Element; Encoder takes an Element and produces a wire dict.
Implementations live in the per-kind ``_codec`` modules under
``protocol/elements/``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ["Decoder", "Encoder"]


@runtime_checkable
class Decoder(Protocol):
    """Per-kind decoder for one wire format.

    Reads a wire dict and returns a fully-constructed Element with the
    tier's ``renderer_factory`` + ``emit`` injected at construction.
    """

    def decode(self, raw: dict[str, object]) -> object: ...


@runtime_checkable
class Encoder(Protocol):
    """Per-kind encoder for one wire format.

    Reads an Element (or Update/Event) and produces a wire dict suitable
    for ``json.dumps``.
    """

    def encode(self, value: object) -> dict[str, object]: ...
