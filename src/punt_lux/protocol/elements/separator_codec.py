"""JsonSeparatorDecoder + JsonSeparatorEncoder — wire codec for ``SeparatorElement``.

The codec body lives in this sibling module rather than on
``SeparatorElement``. ``SeparatorElement.to_dict`` / ``SeparatorElement.from_dict``
remain as short delegators so the runtime-checkable
``domain.element.Element`` Protocol stays satisfied.

The decoder injects the tier's ``renderer_factory`` + ``emit`` at
construction — off the display tier that is the fail-loud sentinel, which
the Display rebinds post-receive. ``id`` is optional here: an anonymous
separator omits it on the wire and decodes to the empty-string sentinel.
Unlike the legacy dataclass codec, this encoder/decoder owns ``tooltip``
directly (the legacy path relied on a generic replace that ABC kinds never
reach).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.protocol.elements._util import strip_none
from punt_lux.protocol.elements.element_wire import ElementWireContext

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.elements.separator import SeparatorElement
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["JsonSeparatorDecoder", "JsonSeparatorEncoder"]


class JsonSeparatorDecoder:
    """Decode a wire dict to a fully-constructed ``SeparatorElement``.

    Constructed once per tier with that tier's ``renderer_factory`` +
    ``emit``; every decoded element is born with the same injected DI.
    Boundary validation (PY-EH-1) routes through ``ElementWireContext`` so a
    non-string ``id`` raises a typed ``ValueError`` with the offending field
    named in the message.
    """

    _rf: RendererFactory
    _emit: Emit
    _cls: type[SeparatorElement]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        element_cls: type[SeparatorElement],
    ) -> Self:
        self = super().__new__(cls)
        self._rf = renderer_factory
        self._emit = emit
        self._cls = element_cls
        return self

    def decode(self, raw: Mapping[str, object]) -> SeparatorElement:
        """Construct a SeparatorElement from a JSON-decoded mapping."""
        ctx = ElementWireContext.for_kind("separator")
        return self._cls(
            renderer_factory=self._rf,
            emit=self._emit,
            id=ctx.optional_str(raw, "id", default=""),
            tooltip=ctx.optional_nullable_str(raw, "tooltip"),
        )


class JsonSeparatorEncoder:
    """Encode a ``SeparatorElement`` to its JSON-compatible wire dict.

    Stateless. ``id`` is omitted when it is the empty anonymous sentinel and
    ``tooltip`` when absent, so the wire shape matches the legacy dataclass
    codec byte-for-byte; ``kind`` is always emitted.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode(self, elem: SeparatorElement) -> dict[str, object]:
        """Serialize a SeparatorElement to a JSON-compatible dict."""
        # ``id`` "" anonymous sentinel flattens to None so strip_none drops it.
        return strip_none(
            {
                "kind": elem.kind,
                "id": elem.id or None,
                "tooltip": elem.tooltip,
            }
        )
