"""JsonTabBarDecoder + JsonTabBarEncoder — wire codec for the ABC ``TabBarElement``.

Mirrors the group codec (child recursion plus the shared all-ABC gate) and the
checkbox codec (a built-in state-sync handler registered before any wire
handlers, so ``fire`` has a bucket and the Hub has authoritative behavior when
``TabChanged`` crosses back).

Each tab carries a stable ``tab_id`` assigned by ``TabIdSynthesizer`` — the
agent ``id``, else a content slug of the label, never a positional index.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, Self, cast

from punt_lux.domain.container_interaction import TabChanged
from punt_lux.protocol.elements.container_dispatch import dispatch
from punt_lux.protocol.elements.element_wire import ElementWireContext
from punt_lux.protocol.elements.tab import Tab
from punt_lux.protocol.elements.tab_id_synthesizer import TabIdSynthesizer
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from punt_lux.domain.element_abc import Element
    from punt_lux.protocol.elements.tab_bar import TabBarElement
    from punt_lux.protocol.handler_decoder import HandlerDecoder

__all__ = ["JsonTabBarDecoder", "JsonTabBarEncoder"]

# Injected child decoder: the tier's ``element_from_dict`` bound method.
type DecodeElement = Callable[[dict[str, Any]], object]

_TAB_EVENT_TYPES: dict[str, type[TabChanged]] = {"tab_changed": TabChanged}


class _UpdateActiveTabHandler:
    """Serializable handler that mirrors the active tab on a tab change.

    On the Hub side it updates the authoritative ``active_tab`` through
    ``apply_patch``; on the Display side ``wrap_handlers_for_remote`` folds it
    into a forward-only ``RemoteDispatchGroup``, so the Display never runs it.
    """

    _elem: TabBarElement

    def __new__(cls, elem: TabBarElement) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        return self

    def __reduce__(self) -> tuple[object, ...]:
        return (object.__new__, (type(self),), {"_elem": self._elem})

    def __setstate__(self, state: dict[str, object]) -> None:
        for key, value in state.items():
            object.__setattr__(self, key, value)

    @trace
    def __call__(self, event: TabChanged) -> None:
        self._elem.apply_patch({"active_tab": event.tab_id})


class JsonTabBarDecoder:
    """Decode a wire dict to a fully-constructed ABC ``TabBarElement``.

    Constructed once per tier. Assigns each tab a stable ``tab_id`` via
    ``TabIdSynthesizer``, recurses tab children, registers the built-in
    ``_UpdateActiveTabHandler``, then installs wire-declared handlers.
    """

    _decode_element: DecodeElement
    _cls: type[TabBarElement]
    _handler_decoder: HandlerDecoder[TabChanged]

    def __new__(
        cls,
        *,
        decode_element: DecodeElement,
        element_cls: type[TabBarElement],
        handler_decoder: HandlerDecoder[TabChanged],
    ) -> Self:
        self = super().__new__(cls)
        self._decode_element = decode_element
        self._cls = element_cls
        self._handler_decoder = handler_decoder
        return self

    @trace
    def decode(self, raw: Mapping[str, object]) -> TabBarElement:
        """Construct the tab bar, recursing tab children through the tier decoder."""
        ctx = ElementWireContext.for_kind("tab_bar")
        tab_ids = TabIdSynthesizer()
        tabs = tuple(
            self._decode_tab(tab, tab_ids)
            for tab in self._require_list(raw.get("tabs"))
        )
        active_tab = ctx.optional_str(raw, "active_tab", default="")
        elem = self._cls(
            id=ctx.require_str(raw, "id"), tabs=tabs, active_tab=active_tab
        )
        elem.add_handler(TabChanged, _UpdateActiveTabHandler(elem))
        self._install_handlers(elem, raw)
        return elem

    def _decode_tab(self, raw_tab: object, tab_ids: TabIdSynthesizer) -> Tab:
        """Decode one wire tab, assigning its stable id from the synthesizer."""
        if not isinstance(raw_tab, Mapping):
            msg = f"tab_bar tab must be a mapping, got {type(raw_tab).__name__}"
            raise TypeError(msg)
        tab = cast("Mapping[str, object]", raw_tab)
        raw_label = tab.get("label")
        label = raw_label if isinstance(raw_label, str) else ""
        tab_id = tab_ids.id_for(tab, label)
        children = tuple(
            self._decode(c) for c in self._require_list(tab.get("children"))
        )
        return Tab(tab_id=tab_id, label=label, children=children)

    def _decode(self, raw_child: object) -> Element:
        """Decode one wire child through the injected tier decoder."""
        child = cast("dict[str, Any]", raw_child)
        return cast("Element", self._decode_element(child))

    def _install_handlers(self, elem: TabBarElement, raw: Mapping[str, object]) -> None:
        """Install tab-changed handlers declared by the wire ``handlers`` list."""
        handlers_raw = raw.get("handlers")
        if handlers_raw is None:
            return
        if not isinstance(handlers_raw, list):
            msg = (
                f"tab_bar 'handlers' must be a list, got {type(handlers_raw).__name__}"
            )
            raise TypeError(msg)
        for i, spec in enumerate(cast("list[object]", handlers_raw)):
            if not isinstance(spec, dict):
                msg = (
                    f"tab_bar 'handlers[{i}]' must be a mapping, "
                    f"got {type(spec).__name__}"
                )
                raise TypeError(msg)
            spec_map = cast("Mapping[str, object]", spec)
            event_type = self._resolve_event_type(spec_map, i)
            handler = self._handler_decoder.decode_spec(spec_map)
            elem.add_handler(event_type, handler)

    @staticmethod
    def _resolve_event_type(spec: Mapping[str, object], index: int) -> type[TabChanged]:
        """Map the wire ``event`` string to its typed event class."""
        event_name = spec.get("event")
        if not isinstance(event_name, str) or not event_name:
            msg = (
                f"tab_bar 'handlers[{index}]' requires an 'event' string, "
                f"got {event_name!r}"
            )
            raise ValueError(msg)
        event_type = _TAB_EVENT_TYPES.get(event_name)
        if event_type is None:
            known = sorted(_TAB_EVENT_TYPES)
            msg = (
                f"tab_bar 'handlers[{index}].event' = {event_name!r} is not "
                f"recognised (expected one of {known})"
            )
            raise ValueError(msg)
        return event_type

    @staticmethod
    def _require_list(raw: object) -> list[object]:
        """Return ``raw`` as a list; ``[]`` absent, raising present-but-not-list.

        Malformed wire is rejected, not silently coerced to empty.
        """
        if raw is None:
            return []
        if not isinstance(raw, list):
            msg = f"tab_bar tabs/children must be a list, got {type(raw).__name__}"
            raise TypeError(msg)
        return cast("list[object]", raw)


class JsonTabBarEncoder:
    """Encode an ABC ``TabBarElement`` to its JSON-compatible wire dict.

    Stateless. Emits each tab's ``id``/``label``/``children`` and ``active_tab``.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode(self, elem: TabBarElement) -> dict[str, object]:
        """Serialize a TabBarElement to a JSON-compatible dict."""
        recurse = dispatch.to_dict
        payload: dict[str, object] = {
            "kind": "tab_bar",
            "id": elem.id,
            "tabs": [
                {
                    "id": tab.tab_id,
                    "label": tab.label,
                    "children": [recurse(child) for child in tab.children],
                }
                for tab in elem.tabs
            ],
            "active_tab": elem.active_tab,
        }
        if elem.tooltip is not None:
            payload["tooltip"] = elem.tooltip
        return payload
