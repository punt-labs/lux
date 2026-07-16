"""Concrete ``AbcKindSpec`` implementations for the three construction shapes.

A migrated kind's decoder is built one of three ways, captured by one class each:

- ``LeafKindSpec`` — a leaf decoder taking ``renderer_factory`` / ``emit`` /
  ``element_cls``, optionally a ``handler_decoder`` built from the tier sink,
  optionally a ``pre_decode`` wire canonicalizer (Button's click/publish sugar).
- ``DialogKindSpec`` — the one leaf whose decoder takes the tier ``publish_sink``
  directly rather than a handler decoder.
- ``ContainerKindSpec`` — a container decoder taking the factory's ``recurse``
  callback plus ``element_cls`` and an optional handler decoder.

Each holds the kind's classes as data (in a ``KindCodec``) and owns the
construction logic (PY-OO-5). The decoder class is constructed dynamically —
the wire dispatch boundary — so the constructed value is ``Any`` until its
``decode`` is re-typed ``KindDecoder``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.element_abc import Element as AbcElement
    from punt_lux.protocol.elements.abc_kind_spec import (
        HandlerBuilder,
        KindCodec,
        KindDecoder,
        TierBinding,
        WirePreDecode,
    )

__all__ = ["ContainerKindSpec", "DialogKindSpec", "LeafKindSpec"]


class LeafKindSpec:
    """A migrated leaf kind decoded through a ``renderer_factory``/``emit`` decoder.

    ``handler_builder`` wires the kind's declarative handlers from the tier
    publish sink when present; ``pre_decode`` canonicalizes wire sugar before
    decode (only Button uses it — for its factory-bound decoder, so the direct
    ``from_dict`` path stays unchanged).
    """

    __slots__ = ("_codec", "_handler_builder", "_kind", "_pre_decode")

    _kind: str
    _codec: KindCodec
    _handler_builder: HandlerBuilder | None
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

    def build_decoder(self, binding: TierBinding) -> KindDecoder:
        """Construct this kind's decoder bound to ``binding``'s tier DI."""
        handler_kwargs: dict[str, object] = {}
        if self._handler_builder is not None:
            handler_kwargs["handler_decoder"] = self._handler_builder(
                binding.publish_sink
            )
        decoder = self._codec.decoder_cls(
            renderer_factory=binding.renderer_factory,
            emit=binding.emit,
            element_cls=self._codec.element_cls,
            **handler_kwargs,
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
        return self._codec.encoder(elem)


class DialogKindSpec:
    """The Dialog kind — a leaf whose decoder takes the tier ``publish_sink``.

    Dialog wires its child Button handlers against a per-dialog model, so its
    decoder is constructed with the sink directly rather than a standalone
    handler decoder. Decoded on the leaf path (it is not a recursing container).
    """

    __slots__ = ("_codec",)

    _codec: KindCodec

    def __new__(cls, *, codec: KindCodec) -> Self:
        self = super().__new__(cls)
        self._codec = codec
        return self

    @property
    def kind(self) -> str:
        """Return ``"dialog"``."""
        return "dialog"

    @property
    def element_type(self) -> type:
        """Return the Dialog element class."""
        return self._codec.element_cls

    @property
    def is_container(self) -> bool:
        """Return ``False`` — Dialog decodes its children internally, not via recurse.

        The Dialog decoder builds its child Buttons itself rather than
        recursing them through the factory, so it dispatches on the leaf path.
        """
        return False

    def build_decoder(self, binding: TierBinding) -> KindDecoder:
        """Construct the Dialog decoder bound to ``binding``'s tier DI."""
        decoder = self._codec.decoder_cls(
            renderer_factory=binding.renderer_factory,
            emit=binding.emit,
            element_cls=self._codec.element_cls,
            publish_sink=binding.publish_sink,
        )
        decode: KindDecoder = decoder.decode
        return decode

    def encode(self, elem: object) -> dict[str, object]:
        """Serialize a Dialog element to its wire dict."""
        return self._codec.encoder(elem)


class ContainerKindSpec:
    """A conditionally-ABC container kind decoded through a recursing decoder.

    The decoder recurses each child wire dict through the factory's own
    ``element_from_dict`` (carried on ``binding.recurse``); ``handler_builder``
    wires the container's own handlers from the tier sink when present.
    """

    __slots__ = ("_codec", "_handler_builder", "_kind")

    _kind: str
    _codec: KindCodec
    _handler_builder: HandlerBuilder | None

    def __new__(
        cls,
        *,
        kind: str,
        codec: KindCodec,
        handler_builder: HandlerBuilder | None = None,
    ) -> Self:
        self = super().__new__(cls)
        self._kind = kind
        self._codec = codec
        self._handler_builder = handler_builder
        return self

    @property
    def kind(self) -> str:
        """Return the wire ``kind`` this container spec decodes."""
        return self._kind

    @property
    def element_type(self) -> type:
        """Return the container element class this kind decodes to."""
        return self._codec.element_cls

    @property
    def is_container(self) -> bool:
        """Return ``True`` — a container recurses its child wire dicts."""
        return True

    def build_decoder(self, binding: TierBinding) -> KindDecoder:
        """Construct this container's decoder bound to ``binding``'s tier DI."""
        recurse_kwargs: dict[str, object] = {
            "decode_element": binding.recurse,
            "element_cls": self._codec.element_cls,
        }
        if self._handler_builder is not None:
            recurse_kwargs["handler_decoder"] = self._handler_builder(
                binding.publish_sink
            )
        decoder = self._codec.decoder_cls(**recurse_kwargs)
        decode: KindDecoder = decoder.decode
        return decode

    def encode(self, elem: object) -> dict[str, object]:
        """Serialize a container element of this kind to its wire dict."""
        return self._codec.encoder(elem)
