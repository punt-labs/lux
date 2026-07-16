"""``DialogKindSpec`` and ``ContainerKindSpec`` — the two non-leaf spec shapes.

- ``DialogKindSpec`` — the one leaf whose decoder takes the tier ``publish_sink``.
- ``ContainerKindSpec`` — a container decoder over the factory's ``recurse``.

Each composes a ``KindCodec`` (PY-OO-5) and constructs its decoder dynamically at
the wire boundary, so it is ``Any`` until ``decode`` is re-typed ``KindDecoder``.
``LeafKindSpec`` — the primary shape — lives in ``abc_leaf_spec``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from punt_lux.protocol.elements.abc_kind_codec import KindCodec
    from punt_lux.protocol.elements.abc_kind_spec import (
        HandlerBuilder,
        KindDecoder,
        TierBinding,
    )

__all__ = ["ContainerKindSpec", "DialogKindSpec"]


class DialogKindSpec:
    """The Dialog kind — a leaf whose decoder takes the tier ``publish_sink``.

    Dialog wires its child Button handlers against a per-dialog model, so its
    decoder is constructed with the sink directly. Decoded on the leaf path.
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
        """Return ``False`` — Dialog is decoded on the leaf path."""
        return False

    @property
    def capabilities(self) -> frozenset[str]:
        """Dialog always wires its child-button handlers via the publish sink."""
        return frozenset({"handlers"})

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
        return self._codec.encode(elem)


class ContainerKindSpec:
    """A conditionally-ABC container kind decoded through a recursing decoder."""

    __slots__ = ("_codec", "_handler_builder", "_kind")

    _kind: str
    _codec: KindCodec
    # genuinely optional — a plain group wires no handlers of its own.
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

    @property
    def capabilities(self) -> frozenset[str]:
        """Return the wire capabilities this container's built decoder carries."""
        return frozenset() if self._handler_builder is None else frozenset({"handlers"})

    def build_decoder(self, binding: TierBinding) -> KindDecoder:
        """Construct this container's decoder bound to ``binding``'s tier DI."""
        extra: dict[str, object] = {}
        if self._handler_builder is not None:
            extra["handler_decoder"] = self._handler_builder(binding.publish_sink)
        decoder = self._codec.decoder_cls(
            decode_element=binding.recurse,
            element_cls=self._codec.element_cls,
            **extra,
        )
        decode: KindDecoder = decoder.decode
        return decode

    def encode(self, elem: object) -> dict[str, object]:
        """Serialize a container element of this kind to its wire dict."""
        return self._codec.encode(elem)
