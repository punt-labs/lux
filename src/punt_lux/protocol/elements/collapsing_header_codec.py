"""JsonCollapsingHeaderDecoder + JsonCollapsingHeaderEncoder — wire codec for the
ABC ``CollapsingHeaderElement``.

Mirrors two exemplars: the group codec (child recursion plus the shared all-ABC
gate) and the checkbox codec (a built-in state-sync handler registered before
any wire handlers, so ``fire`` has a bucket and the Hub has authoritative
behavior when ``HeaderToggled`` crosses back).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, Self, cast

from punt_lux.domain.container_interaction import HeaderToggled
from punt_lux.protocol.elements.container_dispatch import dispatch
from punt_lux.protocol.elements.element_wire import ElementWireContext
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from punt_lux.domain.element_abc import Element
    from punt_lux.protocol.elements.collapsing_header import CollapsingHeaderElement
    from punt_lux.protocol.handler_decoder import HandlerDecoder

__all__ = ["JsonCollapsingHeaderDecoder", "JsonCollapsingHeaderEncoder"]

# Injected child decoder: the tier's ``element_from_dict`` bound method.
type DecodeElement = Callable[[dict[str, Any]], object]

_HEADER_EVENT_TYPES: dict[str, type[HeaderToggled]] = {"header_toggled": HeaderToggled}


class _UpdateOpenHandler:
    """Serializable handler that mirrors a header's open flag on toggle.

    On the Hub side it updates the authoritative ``open`` through ``apply_patch``;
    on the Display side ``wrap_handlers_for_remote`` folds it into a forward-only
    ``RemoteDispatchGroup``, so the Display never runs it.
    """

    _elem: CollapsingHeaderElement

    def __new__(cls, elem: CollapsingHeaderElement) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        return self

    def __reduce__(self) -> tuple[object, ...]:
        return (object.__new__, (type(self),), {"_elem": self._elem})

    def __setstate__(self, state: dict[str, object]) -> None:
        for key, value in state.items():
            object.__setattr__(self, key, value)

    @trace
    def __call__(self, event: HeaderToggled) -> None:
        self._elem.apply_patch({"open": event.open})


class JsonCollapsingHeaderDecoder:
    """Decode a wire dict to a fully-constructed ABC ``CollapsingHeaderElement``.

    Constructed once per tier. Always registers the built-in ``_UpdateOpenHandler``
    for state sync, then installs any wire-declared ``handlers``.
    """

    _decode_element: DecodeElement
    _cls: type[CollapsingHeaderElement]
    _handler_decoder: HandlerDecoder[HeaderToggled]

    def __new__(
        cls,
        *,
        decode_element: DecodeElement,
        element_cls: type[CollapsingHeaderElement],
        handler_decoder: HandlerDecoder[HeaderToggled],
    ) -> Self:
        self = super().__new__(cls)
        self._decode_element = decode_element
        self._cls = element_cls
        self._handler_decoder = handler_decoder
        return self

    @trace
    def decode(self, raw: Mapping[str, object]) -> CollapsingHeaderElement:
        """Construct the header, recursing children through the tier decoder."""
        ctx = ElementWireContext.for_kind("collapsing_header")
        children = tuple(
            self._decode(c) for c in self._require_list(raw.get("children"))
        )
        elem = self._cls(
            id=ctx.require_str(raw, "id"),
            label=ctx.optional_str(raw, "label", default=""),
            open=ctx.optional_bool(raw, "open", default=False),
            children=children,
            tooltip=ctx.optional_nullable_str(raw, "tooltip"),
        )
        elem.add_handler(HeaderToggled, _UpdateOpenHandler(elem))
        self._install_handlers(elem, raw)
        return elem

    def _decode(self, raw_child: object) -> Element:
        """Decode one wire child through the injected tier decoder."""
        child = cast("dict[str, Any]", raw_child)
        return cast("Element", self._decode_element(child))

    def _install_handlers(
        self, elem: CollapsingHeaderElement, raw: Mapping[str, object]
    ) -> None:
        """Install header-toggled handlers declared by the wire ``handlers`` list."""
        handlers_raw = raw.get("handlers")
        if handlers_raw is None:
            return
        if not isinstance(handlers_raw, list):
            msg = (
                "collapsing_header 'handlers' must be a list, got "
                f"{type(handlers_raw).__name__}"
            )
            raise TypeError(msg)
        for i, spec in enumerate(cast("list[object]", handlers_raw)):
            if not isinstance(spec, dict):
                msg = (
                    f"collapsing_header 'handlers[{i}]' must be a mapping, "
                    f"got {type(spec).__name__}"
                )
                raise TypeError(msg)
            spec_map = cast("Mapping[str, object]", spec)
            event_type = self._resolve_event_type(spec_map, i)
            handler = self._handler_decoder.decode_spec(spec_map)
            elem.add_handler(event_type, handler)

    @staticmethod
    def _resolve_event_type(
        spec: Mapping[str, object], index: int
    ) -> type[HeaderToggled]:
        """Map the wire ``event`` string to its typed event class."""
        event_name = spec.get("event")
        if not isinstance(event_name, str):
            msg = (
                f"collapsing_header 'handlers[{index}]' requires an 'event' "
                f"string, got {event_name!r}"
            )
            raise ValueError(msg)
        event_type = _HEADER_EVENT_TYPES.get(event_name)
        if event_type is None:
            known = sorted(_HEADER_EVENT_TYPES)
            msg = (
                f"collapsing_header 'handlers[{index}].event' = {event_name!r} is "
                f"not recognised (expected one of {known})"
            )
            raise ValueError(msg)
        return event_type

    @staticmethod
    def _require_list(raw: object) -> list[object]:
        """Return ``raw`` as a list; ``[]`` absent, raising a present non-list."""
        if raw is None:
            return []
        if not isinstance(raw, list):
            msg = f"collapsing_header children must be a list, got {type(raw).__name__}"
            raise TypeError(msg)
        return cast("list[object]", raw)


class JsonCollapsingHeaderEncoder:
    """Encode an ABC ``CollapsingHeaderElement`` to its JSON-compatible wire dict.

    Stateless. Emits ``open`` (the single view field, no ``default_open``) and
    ``children`` always, ``tooltip`` only when set.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode(self, elem: CollapsingHeaderElement) -> dict[str, object]:
        """Serialize a CollapsingHeaderElement to a JSON-compatible dict."""
        recurse = dispatch.to_dict
        payload: dict[str, object] = {
            "kind": "collapsing_header",
            "id": elem.id,
            "label": elem.label,
            "open": elem.open,
            "children": [recurse(child) for child in elem.children],
        }
        if elem.tooltip is not None:
            payload["tooltip"] = elem.tooltip
        return payload
