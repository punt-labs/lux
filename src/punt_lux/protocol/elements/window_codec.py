"""JsonWindowDecoder + JsonWindowEncoder — wire codec for the ABC WindowElement.

A display-only container codec: it recurses children through the injected tier
decoder (like the group codec) and maps the flat window wire fields onto the
composed :class:`WindowPlacement` and :class:`WindowFlags` value objects. No
handler wiring — a window declares no interaction. Child recursion is injected so
a nested all-ABC window decodes exactly as the top-level factory would.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, Self, cast

from punt_lux.protocol.elements.container_dispatch import dispatch
from punt_lux.protocol.elements.element_wire import ElementWireContext
from punt_lux.protocol.elements.window_chrome import WindowFlags, WindowPlacement

if TYPE_CHECKING:
    from punt_lux.domain.element_abc import Element
    from punt_lux.protocol.elements.window import WindowElement

__all__ = ["JsonWindowDecoder", "JsonWindowEncoder"]

# Injected child decoder: the tier's ``element_from_dict`` bound method.
type DecodeElement = Callable[[dict[str, Any]], object]


class JsonWindowDecoder:
    """Decode a wire dict to a fully-constructed ABC ``WindowElement``."""

    _decode_element: DecodeElement
    _cls: type[WindowElement]

    def __new__(
        cls,
        *,
        decode_element: DecodeElement,
        element_cls: type[WindowElement],
    ) -> Self:
        self = super().__new__(cls)
        self._decode_element = decode_element
        self._cls = element_cls
        return self

    def decode(self, raw: Mapping[str, object]) -> WindowElement:
        """Construct a WindowElement, recursing children through the tier decoder."""
        ctx = ElementWireContext.for_kind("window")
        children = tuple(self._decode(c) for c in self._as_list(raw.get("children")))
        return self._cls(
            id=ctx.require_id(raw),
            title=ctx.optional_str(raw, "title", default=""),
            placement=WindowPlacement.from_wire(raw),
            flags=WindowFlags.from_wire(raw),
            children=children,
            tooltip=ctx.optional_nullable_str(raw, "tooltip"),
        )

    def _decode(self, raw_child: object) -> Element:
        """Decode one wire child through the injected tier decoder."""
        child = cast("dict[str, Any]", raw_child)
        return cast("Element", self._decode_element(child))

    @staticmethod
    def _as_list(raw: object) -> list[object]:
        """Return ``raw`` as a list of wire objects, or empty when absent."""
        if isinstance(raw, list):
            return cast("list[object]", raw)
        return []


class JsonWindowEncoder:
    """Encode an ABC ``WindowElement`` to its JSON-compatible wire dict.

    Stateless. Emits the legacy window wire shape — ``title`` and the four
    placement scalars and ``children`` always, each set flag only when on,
    ``tooltip`` only when present — so an all-ABC window re-encodes byte-for-byte.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode(self, elem: WindowElement) -> dict[str, object]:
        """Serialize a WindowElement to a JSON-compatible dict."""
        recurse = dispatch.to_dict
        payload: dict[str, object] = {
            "kind": "window",
            "id": elem.id,
            "title": elem.title,
            **elem.placement.to_wire(),
            "children": [recurse(child) for child in elem.children],
        }
        payload.update(elem.flags.to_wire())
        if elem.tooltip is not None:
            payload["tooltip"] = elem.tooltip
        return payload
