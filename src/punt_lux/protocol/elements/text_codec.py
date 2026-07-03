"""JsonTextDecoder + JsonTextEncoder — wire codec for ``TextElement``.

The codec body lives in this sibling module rather than on
``TextElement``. ``TextElement.to_dict`` / ``TextElement.from_dict``
remain as short delegators so the runtime-checkable
``domain.element.Element`` Protocol stays satisfied.

The decoder injects the tier's ``renderer_factory`` + ``emit`` at
construction so the element is born with its DI wired in. The encoder
takes the element state directly — no intermediate render product.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.protocol.elements._util import strip_none
from punt_lux.protocol.elements.element_wire import ElementWireContext

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.elements.text import TextElement
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["JsonTextDecoder", "JsonTextEncoder"]


class JsonTextDecoder:
    """Decode a wire dict to a fully-constructed ``TextElement``.

    Constructed once per tier with that tier's ``renderer_factory`` +
    ``emit``; every decoded element is born with the same injected DI.
    Boundary validation (PY-EH-1) routes through ``ElementWireContext`` so
    a non-string ``id`` raises a typed ``ValueError`` with the offending
    field named in the message.

    The decoder holds a reference to the ``TextElement`` class (passed
    in at construction) so this module can be imported by ``text.py``
    without circular-import grief; ``text.py``'s delegators construct a
    decoder with ``cls`` and call ``.decode(d)``.
    """

    _rf: RendererFactory
    _emit: Emit
    _cls: type[TextElement]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        element_cls: type[TextElement],
    ) -> Self:
        self = super().__new__(cls)
        self._rf = renderer_factory
        self._emit = emit
        self._cls = element_cls
        return self

    def decode(self, raw: Mapping[str, object]) -> TextElement:
        """Construct a TextElement from a JSON-decoded mapping."""
        ctx = ElementWireContext.for_kind("text")
        # PR-2 dataclass codec accepted ``{"color": null}`` via
        # optional_nullable_str; preserve wire backward-compat by
        # coercing None to the empty-string default.
        color_raw = ctx.optional_nullable_str(raw, "color")
        return self._cls(
            renderer_factory=self._rf,
            emit=self._emit,
            id=ctx.require_str(raw, "id"),
            content=ctx.require_str(raw, "content"),
            style=ctx.optional_nullable_str(raw, "style"),
            tooltip=ctx.optional_nullable_str(raw, "tooltip"),
            color=color_raw if color_raw is not None else "",
        )


class JsonTextEncoder:
    """Encode a ``TextElement`` to its JSON-compatible wire dict.

    Stateless. ``style``, ``tooltip``, and ``color`` are omitted when
    absent so the wire shape matches the PR-2 dataclass codec byte-for-byte.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode(self, elem: TextElement) -> dict[str, object]:
        """Serialize a TextElement to a JSON-compatible dict."""
        # ``color`` "" sentinel flattens to None so strip_none drops it.
        return strip_none(
            {
                "kind": elem.kind,
                "id": elem.id,
                "content": elem.content,
                "style": elem.style,
                "tooltip": elem.tooltip,
                "color": elem.color or None,
            }
        )
