"""JsonElementFactory — top-level wire decoder dispatching by ``kind``.

The io-model inbound dispatcher. One instance per tier (constructed at
startup with that tier's ``RendererFactory`` + ``Emit``); each
``decode(raw)`` call routes to the per-kind decoder for ``raw["kind"]``.

Currently ships Text-only dispatch. Additional kinds register as their
decoders migrate from the legacy ``ElementCodec`` path to the io-model.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.elements.text_codec import JsonTextDecoder

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["JsonElementFactory"]


class JsonElementFactory:
    """Dispatch wire dicts to per-kind decoders by their ``kind`` field.

    Holds the tier's ``RendererFactory`` + ``Emit`` so every decoded
    element is born with the same injected DI. ``kind`` validation lives
    upstream in ``element_from_dict`` so all element kinds share one
    boundary check.

    Per-kind decoders are constructed once and reused across every
    ``decode()`` call — the decoders carry only injected DI, so a single
    instance handles every wire dict for that kind without per-call
    allocation on the hot decode path.
    """

    _rf: RendererFactory
    _emit: Emit
    _text_decoder: JsonTextDecoder

    def __new__(cls, *, renderer_factory: RendererFactory, emit: Emit) -> Self:
        self = super().__new__(cls)
        self._rf = renderer_factory
        self._emit = emit
        self._text_decoder = JsonTextDecoder(
            renderer_factory=renderer_factory,
            emit=emit,
            element_cls=TextElement,
        )
        return self

    def decode(self, raw: Mapping[str, object]) -> TextElement:
        """Dispatch by ``raw["kind"]`` to the per-kind decoder."""
        kind = raw.get("kind")
        if kind == "text":
            return self._text_decoder.decode(raw)
        msg = f"JsonElementFactory has no decoder for kind={kind!r}"
        raise ValueError(msg)
