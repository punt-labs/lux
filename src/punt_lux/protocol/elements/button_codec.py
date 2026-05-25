"""JsonButtonDecoder + JsonButtonEncoder — wire codec for ``ButtonElement``.

The codec sits beside its element class (mirrors the ``text`` / ``text_codec``
split landed in PR 3). ``ButtonElement.to_dict`` / ``from_dict`` remain on
the class as short delegators so the runtime-checkable
``domain.element.Element`` Protocol stays satisfied.

The decoder receives the tier's ``renderer_factory`` and ``emit`` plus an
optional ``handler_decoder`` from the wire dispatcher. When the wire spec
carries a ``"handlers"`` list, the decoder uses ``handler_decoder`` to
turn each entry into a typed ``Handler[ButtonClicked]`` and installs it
on the constructed element via ``add_handler``. The encoder is stateless
and writes the same fields the dataclass codec wrote, byte-for-byte.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast

from punt_lux.domain.interaction import ButtonClicked
from punt_lux.protocol.elements._util import strip_none
from punt_lux.protocol.elements.element_wire import ElementWireContext

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.elements.button import ButtonElement
    from punt_lux.protocol.handler_decoder import HandlerDecoder
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["JsonButtonDecoder", "JsonButtonEncoder"]


class JsonButtonDecoder:
    """Decode a wire dict to a fully-constructed ``ButtonElement``.

    Constructed once per tier with that tier's ``renderer_factory``,
    ``emit``, and (optionally) a ``HandlerDecoder[ButtonClicked]`` wired
    to the Button handler catalog. When the wire spec omits ``handlers``
    the decoder skips handler installation; the element ABC is born with
    an empty registry which subsequent ``add_handler`` calls populate.
    """

    _rf: RendererFactory
    _emit: Emit
    _cls: type[ButtonElement]
    _handler_decoder: HandlerDecoder[ButtonClicked] | None

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        element_cls: type[ButtonElement],
        handler_decoder: HandlerDecoder[ButtonClicked] | None = None,
    ) -> Self:
        self = super().__new__(cls)
        self._rf = renderer_factory
        self._emit = emit
        self._cls = element_cls
        self._handler_decoder = handler_decoder
        return self

    def decode(self, raw: Mapping[str, object]) -> ButtonElement:
        """Construct a ButtonElement from a JSON-decoded mapping."""
        ctx = ElementWireContext.for_kind("button")
        elem = self._cls(
            renderer_factory=self._rf,
            emit=self._emit,
            id=ctx.require_str(raw, "id"),
            label=ctx.optional_str(raw, "label", default=""),
            action=ctx.optional_nullable_str(raw, "action"),
            disabled=ctx.optional_bool(raw, "disabled", default=False),
            small=ctx.optional_bool(raw, "small", default=False),
            arrow=ctx.optional_nullable_str(raw, "arrow"),
            tooltip=ctx.optional_nullable_str(raw, "tooltip"),
        )
        self._install_handlers(elem, raw)
        return elem

    def _install_handlers(self, elem: ButtonElement, raw: Mapping[str, object]) -> None:
        """Install click handlers declared by the wire ``handlers`` list."""
        if self._handler_decoder is None:
            return
        handlers_raw = raw.get("handlers")
        if handlers_raw is None:
            return
        if not isinstance(handlers_raw, list):
            msg = f"button 'handlers' must be a list, got {type(handlers_raw).__name__}"
            raise TypeError(msg)
        for i, spec in enumerate(cast("list[object]", handlers_raw)):
            if not isinstance(spec, dict):
                msg = (
                    f"button 'handlers[{i}]' must be a mapping, "
                    f"got {type(spec).__name__}"
                )
                raise TypeError(msg)
            handler = self._handler_decoder.decode_spec(
                cast("Mapping[str, object]", spec)
            )
            elem.add_handler(ButtonClicked, handler)


class JsonButtonEncoder:
    """Encode a ``ButtonElement`` to its JSON-compatible wire dict.

    Stateless. Default fields are omitted so the wire shape matches the
    PR-2 dataclass codec byte-for-byte.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode(self, elem: ButtonElement) -> dict[str, object]:
        """Serialize a ButtonElement to a JSON-compatible dict."""
        payload: dict[str, object | None] = {
            "kind": elem.kind,
            "id": elem.id,
            "label": elem.label,
            "action": elem.action,
            "tooltip": elem.tooltip,
        }
        if elem.disabled:
            payload["disabled"] = True
        if elem.small:
            payload["small"] = True
        if elem.arrow is not None:
            payload["arrow"] = elem.arrow
        return strip_none(payload)
