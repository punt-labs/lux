"""JsonMarkdownDecoder + JsonMarkdownEncoder — wire codec for ``MarkdownElement``.

The codec body lives in this sibling module rather than on
``MarkdownElement``. ``MarkdownElement.to_dict`` / ``MarkdownElement.from_dict``
remain as short delegators so the runtime-checkable
``domain.element.Element`` Protocol stays satisfied.

The decoder injects the tier's ``renderer_factory`` + ``emit`` at
construction — off the display tier that is the fail-loud sentinel, which
the Display rebinds post-receive. Unlike the legacy dataclass codec, this
encoder/decoder owns ``tooltip`` directly (the legacy path relied on a
generic replace that ABC kinds never reach).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.protocol.elements._util import strip_none
from punt_lux.protocol.elements.element_wire import ElementWireContext

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.elements.markdown import MarkdownElement
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["JsonMarkdownDecoder", "JsonMarkdownEncoder"]


class JsonMarkdownDecoder:
    """Decode a wire dict to a fully-constructed ``MarkdownElement``.

    Constructed once per tier with that tier's ``renderer_factory`` +
    ``emit``; every decoded element is born with the same injected DI.
    Boundary validation (PY-EH-1) routes through ``ElementWireContext`` so a
    non-string ``content`` or ``id`` raises a typed ``ValueError`` with the
    offending field named in the message.
    """

    _rf: RendererFactory
    _emit: Emit
    _cls: type[MarkdownElement]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        element_cls: type[MarkdownElement],
    ) -> Self:
        self = super().__new__(cls)
        self._rf = renderer_factory
        self._emit = emit
        self._cls = element_cls
        return self

    def decode(self, raw: Mapping[str, object]) -> MarkdownElement:
        """Construct a MarkdownElement from a JSON-decoded mapping."""
        ctx = ElementWireContext.for_kind("markdown")
        return self._cls(
            renderer_factory=self._rf,
            emit=self._emit,
            id=ctx.require_str(raw, "id"),
            content=ctx.require_str(raw, "content"),
            tooltip=ctx.optional_nullable_str(raw, "tooltip"),
        )


class JsonMarkdownEncoder:
    """Encode a ``MarkdownElement`` to its JSON-compatible wire dict.

    Stateless. ``tooltip`` is omitted when absent so the wire shape matches
    the legacy dataclass codec byte-for-byte; ``content`` is always emitted.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode(self, elem: MarkdownElement) -> dict[str, object]:
        """Serialize a MarkdownElement to a JSON-compatible dict."""
        return strip_none(
            {
                "kind": elem.kind,
                "id": elem.id,
                "content": elem.content,
                "tooltip": elem.tooltip,
            }
        )
