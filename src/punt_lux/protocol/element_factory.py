"""JsonElementFactory — top-level wire decoder dispatching by ``kind``.

The io-model inbound dispatcher. One instance per tier (constructed at
startup with that tier's ``RendererFactory`` + ``Emit`` + ``PublishSink``);
each ``decode(raw)`` call routes to the per-kind decoder for ``raw["kind"]``.

Ships Text, Button, and Dialog dispatch. Additional kinds register as
their decoders migrate from the legacy ``ElementCodec`` path to the
io-model.

The ``publish_sink`` is REQUIRED. A factory has no permission to be
constructed without one — its Dialog child decoders would silently
swallow ``publish`` decorators, and its Button child decoder would
silently drop catalog handlers. Both are wire-path silent failures the
directive bans.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.domain.element_abc import Element as AbcElement
from punt_lux.protocol.elements.button import ButtonElement
from punt_lux.protocol.elements.button_codec import JsonButtonDecoder
from punt_lux.protocol.elements.dialog import DialogElement
from punt_lux.protocol.elements.dialog_codec import JsonDialogDecoder
from punt_lux.protocol.elements.text import TextElement
from punt_lux.protocol.elements.text_codec import JsonTextDecoder
from punt_lux.protocol.standalone_button_handler import (
    build_standalone_button_handler_decoder,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.handlers.decorators import PublishSink
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["JsonElementFactory"]


class JsonElementFactory:
    """Dispatch wire dicts to per-kind decoders by their ``kind`` field.

    Holds the tier's ``RendererFactory`` + ``Emit`` + ``PublishSink`` so
    every decoded element is born with the same injected DI. ``kind``
    validation lives upstream in ``element_from_dict`` so all element
    kinds share one boundary check.

    Per-kind decoders are constructed once and reused across every
    ``decode()`` call — the decoders carry only injected DI, so a single
    instance handles every wire dict for that kind without per-call
    allocation on the hot decode path.
    """

    _rf: RendererFactory
    _emit: Emit
    _sink: PublishSink
    _text_decoder: JsonTextDecoder
    _button_decoder: JsonButtonDecoder
    _dialog_decoder: JsonDialogDecoder

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        publish_sink: PublishSink,
    ) -> Self:
        self = super().__new__(cls)
        self._rf = renderer_factory
        self._emit = emit
        self._sink = publish_sink
        self._text_decoder = JsonTextDecoder(
            renderer_factory=renderer_factory,
            emit=emit,
            element_cls=TextElement,
        )
        self._button_decoder = JsonButtonDecoder(
            renderer_factory=renderer_factory,
            emit=emit,
            element_cls=ButtonElement,
            handler_decoder=build_standalone_button_handler_decoder(publish_sink),
        )
        self._dialog_decoder = JsonDialogDecoder(
            renderer_factory=renderer_factory,
            emit=emit,
            element_cls=DialogElement,
            publish_sink=publish_sink,
        )
        return self

    def decode(self, raw: Mapping[str, object]) -> AbcElement:
        """Dispatch by ``raw["kind"]`` to the per-kind decoder."""
        kind = raw.get("kind")
        if kind == "text":
            return self._text_decoder.decode(raw)
        if kind == "button":
            return self._button_decoder.decode(raw)
        if kind == "dialog":
            return self._dialog_decoder.decode(raw)
        msg = f"JsonElementFactory has no decoder for kind={kind!r}"
        raise ValueError(msg)
