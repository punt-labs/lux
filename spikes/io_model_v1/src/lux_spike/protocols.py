"""Renderer + RendererFactory + Decoder + Encoder Protocols.

Per io-model.md §"The Renderer family" and §"The Decoder family":
Protocols define structural contracts; implementations live elsewhere.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable


type Emit = Callable[[object], None]


@runtime_checkable
class Renderer(Protocol):
    """Per-kind renderer for one surface. Leaves implement render();
    composites implement begin() and end()."""

    def render(self) -> None: ...
    def begin(self) -> None: ...
    def end(self) -> None: ...


@runtime_checkable
class RendererFactory(Protocol):
    """Callable that resolves an Element to its per-kind renderer
    for this factory's surface. One factory per Display."""

    def __call__(self, elem: object) -> Renderer: ...


@runtime_checkable
class Decoder(Protocol):
    """Per-kind decoder for one wire format. Reads a wire dict and
    returns a fully-constructed Element with factories injected."""

    def decode(self, raw: dict[str, object]) -> object: ...


@runtime_checkable
class Encoder(Protocol):
    """Per-kind encoder for one wire format. Reads an Element (or
    Update/Event) and produces a wire dict."""

    def encode(self, value: object) -> dict[str, object]: ...
