"""JsonButtonDecoder + JsonButtonEncoder — wire codec for ``ButtonElement``.

The codec sits beside its element class, mirroring the ``text`` /
``text_codec`` split. ``ButtonElement.to_dict`` / ``from_dict`` remain on
the class as short delegators so the runtime-checkable
``domain.element.Element`` Protocol stays satisfied.

The decoder receives the tier's ``renderer_factory`` and ``emit`` plus a
``handler_decoder`` from the wire dispatcher. The ``handler_decoder`` is
REQUIRED — a decoder without one cannot install ``handlers`` entries from
the wire spec, and the directive bans silent drops of declarative
handlers. Construction raises ``TypeError`` if it is missing. Also raises
at decode time when a ``handlers[i].event`` does not match the supported
event vocabulary for ButtonElement (only ``"click"`` today) — a typo or
unsupported event must surface loud, not silently install on the wrong
dispatch slot.
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


# The single wire-event vocabulary the ButtonElement understands. The
# decoder validates each handler spec's ``event`` against this table at
# decode time; an unrecognised event raises ``ValueError`` rather than
# silently installing on the click dispatch slot.
_BUTTON_EVENT_TYPES: dict[str, type[ButtonClicked]] = {"click": ButtonClicked}


class JsonButtonDecoder:
    """Decode a wire dict to a fully-constructed ``ButtonElement``.

    Constructed once per tier with that tier's ``renderer_factory``,
    ``emit``, and a ``HandlerDecoder[ButtonClicked]`` wired to the
    Button handler catalog. The handler decoder is REQUIRED —
    construction raises ``TypeError`` if it is missing, so a wire spec
    carrying ``handlers`` can never silently drop them on the floor.
    Specs without ``handlers`` decode normally; the Element ABC is born
    with an empty registry which subsequent ``add_handler`` calls
    populate.
    """

    _rf: RendererFactory
    _emit: Emit
    _cls: type[ButtonElement]
    _handler_decoder: HandlerDecoder[ButtonClicked]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        element_cls: type[ButtonElement],
        handler_decoder: HandlerDecoder[ButtonClicked],
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
            spec_map = cast("Mapping[str, object]", spec)
            event_type = self._resolve_event_type(spec_map, i)
            handler = self._handler_decoder.decode_spec(spec_map)
            elem.add_handler(event_type, handler)

    @staticmethod
    def _resolve_event_type(
        spec: Mapping[str, object], index: int
    ) -> type[ButtonClicked]:
        """Map the wire ``event`` string to its typed event class.

        Raises ``ValueError`` for an unknown event name so a typo
        ("hover", "doubleclick") cannot silently install on the click
        dispatch slot.
        """
        event_name = spec.get("event")
        if not isinstance(event_name, str) or not event_name:
            msg = (
                f"button 'handlers[{index}]' requires an 'event' string, "
                f"got {event_name!r}"
            )
            raise ValueError(msg)
        event_type = _BUTTON_EVENT_TYPES.get(event_name)
        if event_type is None:
            known = sorted(_BUTTON_EVENT_TYPES)
            msg = (
                f"button 'handlers[{index}].event' = {event_name!r} is not "
                f"recognised (expected one of {known})"
            )
            raise ValueError(msg)
        return event_type


class JsonButtonEncoder:
    """Encode a ``ButtonElement`` to its JSON-compatible wire dict.

    Stateless. Default fields are omitted so the wire shape matches the
    dataclass codec byte-for-byte.
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
