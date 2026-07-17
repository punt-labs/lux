"""JsonSelectableDecoder + JsonSelectableEncoder — wire codec for ``SelectableElement``.

Per the checkbox/checkbox_codec split: the codec body that would otherwise live
on ``SelectableElement`` moves into this sibling module. ``SelectableElement``'s
``to_dict`` / ``from_dict`` remain short delegators so the runtime-checkable
``domain.element.Element`` Protocol stays satisfied.

The decoder injects the tier's ``renderer_factory`` + ``emit`` at construction so
the element is born with its DI wired in, then always installs the built-in
``ApplyPatchOnChange`` state-sync handler on the ``selected`` field — the
checkbox pattern with the ``selected`` wire key.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self, cast

from punt_lux.domain.interaction import ValueChanged
from punt_lux.protocol.elements._util import strip_none
from punt_lux.protocol.elements.element_wire import ElementWireContext
from punt_lux.protocol.elements.value_change_handlers import ApplyPatchOnChange
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.elements.selectable import SelectableElement
    from punt_lux.protocol.handler_decoder import HandlerDecoder
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["JsonSelectableDecoder", "JsonSelectableEncoder"]


_SELECTABLE_EVENT_TYPES: dict[str, type[ValueChanged]] = {"changed": ValueChanged}


class JsonSelectableDecoder:
    """Decode a wire dict to a fully-constructed ``SelectableElement``.

    Constructed once per tier with that tier's ``renderer_factory`` + ``emit`` +
    ``HandlerDecoder``; every decoded element is born with the same injected DI.
    Boundary validation (PY-EH-1) routes through ``ElementWireContext``.

    Parallel to ``JsonCheckboxDecoder``: always registers the built-in
    ``ApplyPatchOnChange`` for state sync, then installs any wire-declared
    handlers from the ``handlers`` key.
    """

    _rf: RendererFactory
    _emit: Emit
    _cls: type[SelectableElement]
    _handler_decoder: HandlerDecoder[ValueChanged]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        element_cls: type[SelectableElement],
        handler_decoder: HandlerDecoder[ValueChanged],
    ) -> Self:
        self = super().__new__(cls)
        self._rf = renderer_factory
        self._emit = emit
        self._cls = element_cls
        self._handler_decoder = handler_decoder
        return self

    @trace
    def decode(self, raw: Mapping[str, object]) -> SelectableElement:
        """Construct a SelectableElement from a JSON-decoded mapping."""
        ctx = ElementWireContext.for_kind("selectable")
        elem = self._cls(
            renderer_factory=self._rf,
            emit=self._emit,
            id=ctx.require_str(raw, "id"),
            label=ctx.optional_str(raw, "label", default=""),
            selected=ctx.optional_bool(raw, "selected", default=False),
            tooltip=ctx.optional_nullable_str(raw, "tooltip"),
        )
        elem.add_handler(ValueChanged, ApplyPatchOnChange(elem, field="selected"))
        self._install_handlers(elem, raw)
        return elem

    def _install_handlers(
        self, elem: SelectableElement, raw: Mapping[str, object]
    ) -> None:
        """Install value-changed handlers declared by the wire ``handlers`` list."""
        handlers_raw = raw.get("handlers")
        if handlers_raw is None:
            return
        if not isinstance(handlers_raw, list):
            msg = (
                f"selectable 'handlers' must be a list, "
                f"got {type(handlers_raw).__name__}"
            )
            raise TypeError(msg)
        for i, spec in enumerate(cast("list[object]", handlers_raw)):
            if not isinstance(spec, dict):
                msg = (
                    f"selectable 'handlers[{i}]' must be a mapping, "
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
    ) -> type[ValueChanged]:
        """Map the wire ``event`` string to its typed event class."""
        event_name = spec.get("event")
        if not isinstance(event_name, str) or not event_name:
            msg = (
                f"selectable 'handlers[{index}]' requires an 'event' string, "
                f"got {event_name!r}"
            )
            raise ValueError(msg)
        event_type = _SELECTABLE_EVENT_TYPES.get(event_name)
        if event_type is None:
            known = sorted(_SELECTABLE_EVENT_TYPES)
            msg = (
                f"selectable 'handlers[{index}].event' = {event_name!r} is not "
                f"recognised (expected one of {known})"
            )
            raise ValueError(msg)
        return event_type


class JsonSelectableEncoder:
    """Encode a ``SelectableElement`` to its JSON-compatible wire dict.

    Stateless. ``selected`` is emitted unconditionally (a False row states
    ``selected: false``) — the design states the value, it does not omit it.
    ``tooltip`` is dropped by ``strip_none`` when absent; a present tooltip now
    round-trips (the legacy ``to_dict`` silently dropped it).
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode(self, elem: SelectableElement) -> dict[str, object]:
        """Serialize a SelectableElement to a JSON-compatible dict."""
        return strip_none(
            {
                "kind": elem.kind,
                "id": elem.id,
                "label": elem.label,
                "selected": elem.selected,
                "tooltip": elem.tooltip,
            }
        )
