"""JsonImageDecoder + JsonImageEncoder — wire codec for ``ImageElement``.

The codec body lives in this sibling module rather than on ``ImageElement``.
``ImageElement.to_dict`` / ``ImageElement.from_dict`` remain as short delegators
so the runtime-checkable ``domain.element.Element`` Protocol stays satisfied.

The decoder injects the tier's ``renderer_factory`` + ``emit`` at construction —
off the display tier that is the fail-loud sentinel, which the Display rebinds
post-receive. It hands ``path`` / ``data`` to the element unresolved; the
element's constructor enforces the one-of (raising on "neither" or "both").
Unlike the legacy dataclass codec, this encoder/decoder owns ``tooltip``
directly (the legacy path relied on a generic replace that ABC kinds never
reach) and the single-key source projection.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.protocol.elements._util import strip_none
from punt_lux.protocol.elements.element_wire import ElementWireContext

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.elements.image import ImageElement
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["JsonImageDecoder", "JsonImageEncoder"]


class JsonImageDecoder:
    """Decode a wire dict to a fully-constructed ``ImageElement``.

    Constructed once per tier with that tier's ``renderer_factory`` + ``emit``;
    every decoded element is born with the same injected DI. Boundary validation
    (PY-EH-1) routes through ``ElementWireContext`` (typed ``id`` / ``width`` /
    ``height``) and the element's ``coerce_format`` (the ``format`` Literal); the
    path-xor-data one-of is enforced by the element constructor.
    """

    _rf: RendererFactory
    _emit: Emit
    _cls: type[ImageElement]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        element_cls: type[ImageElement],
    ) -> Self:
        self = super().__new__(cls)
        self._rf = renderer_factory
        self._emit = emit
        self._cls = element_cls
        return self

    def decode(self, raw: Mapping[str, object]) -> ImageElement:
        """Construct an ImageElement from a JSON-decoded mapping."""
        ctx = ElementWireContext.for_kind("image")
        return self._cls(
            renderer_factory=self._rf,
            emit=self._emit,
            id=ctx.require_id(raw),
            path=ctx.optional_nullable_str(raw, "path"),
            data=ctx.optional_nullable_str(raw, "data"),
            format=self._cls.coerce_format(raw.get("format")),
            alt=ctx.optional_nullable_str(raw, "alt"),
            width=ctx.optional_int(raw, "width"),
            height=ctx.optional_int(raw, "height"),
            tooltip=ctx.optional_nullable_str(raw, "tooltip"),
        )


class JsonImageEncoder:
    """Encode an ``ImageElement`` to its JSON-compatible wire dict.

    Stateless. The source contributes its single owned key (``path`` xor
    ``data``); every other field is omitted when absent so the wire shape
    matches the legacy dataclass codec byte-for-byte; ``kind`` and ``id`` are
    always emitted.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode(self, elem: ImageElement) -> dict[str, object]:
        """Serialize an ImageElement to a JSON-compatible dict."""
        return strip_none(
            {
                "kind": elem.kind,
                "id": elem.id,
                **elem.source.wire(),
                "format": elem.format,
                "alt": elem.alt,
                "width": elem.width,
                "height": elem.height,
                "tooltip": elem.tooltip,
            }
        )
