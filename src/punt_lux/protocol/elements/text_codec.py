"""JsonTextDecoder + JsonTextEncoder — wire codec for ``TextElement``.

Per docs/oo-refactor/pr3-v2.1-design.md §1 row 4 and §4: the codec body
that used to live on ``TextElement`` (PR-2 dataclass) moves into this
sibling module. ``TextElement.to_dict`` / ``TextElement.from_dict``
remain as ≤ 3-line delegators (D5) so the runtime-checkable
``domain.element.Element`` Protocol stays satisfied.

The decoder injects the tier's ``renderer_factory`` + ``emit`` at
construction so the io-model element is born with its DI wired in. The
encoder takes the element state directly — no intermediate render
product (the rejected RemoteRenderer pattern, per ARCHITECTURE_NOTES A3).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

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
        return self._cls(
            renderer_factory=self._rf,
            emit=self._emit,
            id=ctx.require_str(raw, "id"),
            content=ctx.require_str(raw, "content"),
            style=ctx.optional_nullable_str(raw, "style"),
            tooltip=ctx.optional_nullable_str(raw, "tooltip"),
            color=ctx.optional_str(raw, "color", default=""),
        )


class JsonTextEncoder:
    """Encode a ``TextElement`` to its JSON-compatible wire dict.

    Stateless — instances hold no surface context. ``style``, ``tooltip``,
    and ``color`` are omitted when absent (style/tooltip are ``None``,
    color is the empty-string default) so the wire shape matches the
    PR-2 dataclass codec byte-for-byte.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode(self, elem: TextElement) -> dict[str, object]:
        """Serialize a TextElement to a JSON-compatible dict."""
        out: dict[str, object] = {
            "kind": elem.kind,
            "id": elem.id,
            "content": elem.content,
        }
        if elem.style is not None:
            out["style"] = elem.style
        if elem.color:
            out["color"] = elem.color
        return out
