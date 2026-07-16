"""``LeafKindSpec`` — a migrated leaf kind's decode/encode spec.

Handler-wired for interactive leaves; ``pre_decode`` sugar-canonicalizes Button.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.protocol.elements.abc_capability import Capability

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.element_abc import Element as AbcElement
    from punt_lux.protocol.elements.abc_kind_codec import KindCodec
    from punt_lux.protocol.elements.abc_kind_spec import (
        HandlerBuilder,
        KindDecoder,
        TierBinding,
        WirePreDecode,
    )

__all__ = ["LeafKindSpec"]


class LeafKindSpec:
    """A migrated leaf kind decoded through a ``renderer_factory``/``emit`` decoder."""

    __slots__ = ("_codec", "_handler_builder", "_kind", "_pre_decode")

    _kind: str
    _codec: KindCodec
    # genuinely optional — static leaves (text, progress) wire no handlers.
    _handler_builder: HandlerBuilder | None
    # genuinely optional — only Button canonicalizes click/publish wire sugar.
    _pre_decode: WirePreDecode | None

    def __new__(
        cls,
        *,
        kind: str,
        codec: KindCodec,
        handler_builder: HandlerBuilder | None = None,
        pre_decode: WirePreDecode | None = None,
    ) -> Self:
        self = super().__new__(cls)
        self._kind = kind
        self._codec = codec
        self._handler_builder = handler_builder
        self._pre_decode = pre_decode
        return self

    @property
    def kind(self) -> str:
        """Return the wire ``kind`` this spec decodes."""
        return self._kind

    @property
    def element_type(self) -> type:
        """Return the element class this kind decodes to."""
        return self._codec.element_cls

    @property
    def is_container(self) -> bool:
        """Return ``False`` — a leaf never recurses child wire dicts."""
        return False

    @property
    def capabilities(self) -> frozenset[Capability]:
        """Return the wire capabilities this leaf's built decoder carries."""
        wired = (
            (Capability.HANDLERS, self._handler_builder),
            (Capability.PRE_DECODE, self._pre_decode),
        )
        return frozenset(tag for tag, wiring in wired if wiring is not None)

    def build_decoder(self, binding: TierBinding) -> KindDecoder:
        """Construct this kind's decoder bound to ``binding``'s tier DI."""
        extra: dict[str, object] = {}
        if self._handler_builder is not None:
            extra["handler_decoder"] = self._handler_builder(binding.publish_sink)
        decoder = self._codec.decoder_cls(
            renderer_factory=binding.renderer_factory,
            emit=binding.emit,
            element_cls=self._codec.element_cls,
            **extra,
        )
        decode: KindDecoder = decoder.decode
        if self._pre_decode is None:
            return decode
        pre = self._pre_decode

        def _decode(raw: Mapping[str, object]) -> AbcElement:
            return decode(pre(raw))

        return _decode

    def encode(self, elem: object) -> dict[str, object]:
        """Serialize an element of this kind to its wire dict."""
        return self._codec.encode(elem)
