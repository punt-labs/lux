"""The tier DI bundle, the per-kind codec triple, and the ABC decode contract.

``TierBinding`` groups the four dependencies a decoder needs at construction —
the tier's renderer factory, emit channel, publish sink, and the factory's own
recursive ``element_from_dict`` — so a spec's ``build_decoder`` takes one object
instead of four arguments (PY-OO-3).

``KindCodec`` bundles the three classes that make up one kind's wire codec —
element class, decoder class, encoder — mirroring ``ElementCodec``'s
(class, to_dict, from_dict) triple for the legacy path.

``AbcKindSpec`` is the structural contract every migrated kind's spec satisfies
(Protocol, not a base class): it names the kind, its element class, whether it
is a container, and how to build its decoder and encode its elements.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from punt_lux.domain.element_abc import Element as AbcElement
    from punt_lux.domain.handlers.decorators import PublishSink
    from punt_lux.protocol.elements.container_dispatch import RecurseFromDict
    from punt_lux.protocol.handler_decoder import HandlerDecoder
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = [
    "AbcKindSpec",
    "HandlerBuilder",
    "KindCodec",
    "KindDecoder",
    "KindEncoder",
    "TierBinding",
    "WirePreDecode",
]

# The decoded-element callback the factory dispatches to per kind. Defined at
# runtime as a lazy PEP 695 alias so the TYPE_CHECKING-only element type is
# never evaluated at import.
type KindDecoder = Callable[[Mapping[str, object]], AbcElement]
# The per-kind stateless encoder's bound ``encode``; element types vary per
# kind, so the parameter stays untyped at this wire-dispatch boundary.
type KindEncoder = Callable[..., dict[str, object]]
# Builds a kind's handler decoder from the tier publish sink. The event type
# varies per kind (ButtonClicked, CheckboxToggled, …); the registry cannot
# name it, so it is ``Any`` at this wire-dispatch boundary (PY-TS-9).
type HandlerBuilder = Callable[[PublishSink], HandlerDecoder[Any]]
# A per-kind wire canonicalizer applied before decode (Button's click/publish
# sugar). Maps a raw wire dict to a canonical one.
type WirePreDecode = Callable[[Mapping[str, object]], Mapping[str, object]]


@dataclass(frozen=True, slots=True)
class TierBinding:
    """The tier-scoped dependency injection a per-kind decoder is built with."""

    renderer_factory: RendererFactory
    emit: Emit
    publish_sink: PublishSink
    recurse: RecurseFromDict


@dataclass(frozen=True, slots=True)
class KindCodec:
    """One kind's wire codec: element class, decoder class, encoder.

    ``decoder_cls`` is a ``JsonXDecoder`` class constructed dynamically at the
    wire boundary — the same dynamic dispatch ``ElementCodec`` performs — so it
    is typed ``Any`` here (PY-TS-9); the constructed decoder's ``decode`` is
    re-typed ``KindDecoder`` by the spec.
    """

    element_cls: type
    decoder_cls: Any  # JsonXDecoder class; constructed at the wire boundary
    encoder: KindEncoder


@runtime_checkable
class AbcKindSpec(Protocol):
    """One migrated kind's decode/encode knowledge (structural contract)."""

    @property
    def kind(self) -> str: ...
    @property
    def element_type(self) -> type: ...
    @property
    def is_container(self) -> bool: ...
    def build_decoder(self, binding: TierBinding) -> KindDecoder: ...
    def encode(self, elem: object) -> dict[str, object]: ...
