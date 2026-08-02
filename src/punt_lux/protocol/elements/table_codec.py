"""JsonTableDecoder + JsonTableEncoder — wire codec for the ABC ``TableElement``.

Mirrors the checkbox codec (a built-in state-sync handler registered before any
wire handlers, so ``fire`` has a bucket and the Hub has authoritative behavior
when ``RowSelectionChanged`` crosses back) and the tab_bar codec (the handler is
a small serializable class beside the decoder, not the field-parameterised
``ApplyPatchOnChange``, because the selection carries a *set* plus an anchor).

The ``key_column`` accepts a column index or a column name; a name is resolved
to its index here, and a name absent from ``columns`` is a decode error naming
the offending name. An out-of-range *index* is kept for ``validate`` to report
(a selectable grid needs a real key column). ``rows``/``columns`` structural
shape is a decode error; cell content is a ``validate`` concern (DES-039).
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Self, cast

from punt_lux.domain.handlers.publish_sink import PublishSink
from punt_lux.domain.selection_interaction import RowSelectionChanged
from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.element_wire import ElementWireContext
from punt_lux.protocol.elements.table_flags import TableFlags
from punt_lux.protocol.elements.table_selection_model import SelectionMode
from punt_lux.protocol.elements.table_wire import TableWire
from punt_lux.protocol.raising_publish_sink import RaisingPublishSink
from punt_lux.protocol.standalone_row_selection_handler import (
    build_standalone_row_selection_handler_decoder,
)
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.elements.table import TableElement
    from punt_lux.protocol.handler_decoder import HandlerDecoder
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = [
    "JsonTableDecoder",
    "JsonTableEncoder",
    "decode_table_from_dict",
    "install_selection_sync",
]

_SELECTION_MODES: frozenset[str] = frozenset({"none", "single", "multi"})
_ROW_EVENT_TYPES: dict[str, type[RowSelectionChanged]] = {
    "row_selection_changed": RowSelectionChanged
}


def install_selection_sync(elem: TableElement) -> None:
    """Register the built-in selection state-sync handler on ``elem``.

    The single install point for the state-sync handler, so a decoded table and
    a server-side-constructed one (the show_table composition) mirror their
    selection the same way. A ``none``-mode grid is display-only — it carries no
    selection machinery — so the handler is not installed on it.
    """
    if elem.selection_mode == "none":
        return
    elem.add_handler(RowSelectionChanged, _UpdateSelectionHandler(elem))


class _UpdateSelectionHandler:
    """Serializable handler that mirrors the selection on a row-selection change.

    On the Hub side it updates the authoritative selection through
    ``apply_patch`` (the set *and* the anchor); on the Display side
    ``wrap_handlers_for_remote`` folds it into a forward-only
    ``RemoteDispatchGroup``, so the Display never runs it.
    """

    _elem: TableElement

    def __new__(cls, elem: TableElement) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        return self

    def __reduce__(self) -> tuple[object, ...]:
        return (object.__new__, (type(self),), {"_elem": self._elem})

    def __setstate__(self, state: dict[str, object]) -> None:
        for key, value in state.items():
            object.__setattr__(self, key, value)

    @trace
    def __call__(self, event: RowSelectionChanged) -> None:
        self._elem.apply_patch(
            {"selected_row_ids": list(event.row_ids), "anchor_row_id": event.anchor}
        )


class JsonTableDecoder:
    """Decode a wire dict to a fully-constructed ABC ``TableElement``.

    Constructed once per tier with that tier's ``renderer_factory`` + ``emit`` +
    ``HandlerDecoder``. Registers the built-in ``_UpdateSelectionHandler`` for
    state sync, then installs any wire-declared handlers (the business-publish
    path of Decision 1).
    """

    _rf: RendererFactory
    _emit: Emit
    _cls: type[TableElement]
    _handler_decoder: HandlerDecoder[RowSelectionChanged]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        element_cls: type[TableElement],
        handler_decoder: HandlerDecoder[RowSelectionChanged],
    ) -> Self:
        self = super().__new__(cls)
        self._rf = renderer_factory
        self._emit = emit
        self._cls = element_cls
        self._handler_decoder = handler_decoder
        return self

    @trace
    def decode(self, raw: Mapping[str, object]) -> TableElement:
        """Construct a TableElement from a JSON-decoded mapping."""
        ctx = ElementWireContext.for_kind("table")
        columns = TableWire.columns_from_wire(raw.get("columns", []))
        elem = self._cls(
            renderer_factory=self._rf,
            emit=self._emit,
            id=ctx.require_id(raw),
            columns=columns,
            rows=TableWire.rows_from_wire(raw.get("rows", [])),
            flags=self._decode_flags(ctx, raw),
            column_widths=self._decode_column_widths(raw),
            key_column=self._resolve_key_column(raw.get("key_column", 0), columns),
            selection_mode=self._decode_mode(raw),
            selected_row_ids=frozenset(self._decode_selected_ids(ctx, raw)),
            anchor_row_id=ctx.optional_str(raw, "anchor_row_id", default=""),
            tooltip=ctx.optional_nullable_str(raw, "tooltip"),
            scroll_reserve_lines=ctx.optional_int_with_default(
                raw, "scroll_reserve_lines", default=0
            ),
        )
        install_selection_sync(elem)
        self._install_handlers(elem, raw)
        return elem

    @staticmethod
    def _decode_flags(ctx: ElementWireContext, raw: Mapping[str, object]) -> TableFlags:
        """Decode the render flags; an absent ``flags`` keeps the defaults."""
        if "flags" not in raw:
            return TableFlags()
        return TableFlags.from_wire(ctx.optional_string_list(raw, "flags"))

    @staticmethod
    def _decode_column_widths(raw: Mapping[str, object]) -> tuple[float, ...]:
        """Decode explicit column widths, ``()`` when absent."""
        if "column_widths" not in raw:
            return ()
        value = raw["column_widths"]
        if not isinstance(value, list):
            msg = f"column_widths must be a list of numbers, got {type(value).__name__}"
            raise ValueError(msg)
        widths: list[float] = []
        for index, item in enumerate(cast("list[object]", value)):
            if isinstance(item, bool) or not isinstance(item, int | float):
                got = type(item).__name__
                msg = f"column_widths[{index}] must be a number, got {got}"
                raise ValueError(msg)
            if not math.isfinite(item):
                # A non-finite stretch weight (nan/inf) into table_setup_column is
                # undefined behavior; reject it at the wire boundary, like the
                # repo's other numeric decode paths.
                msg = f"column_widths[{index}] must be finite, got {item}"
                raise ValueError(msg)
            widths.append(float(item))
        return tuple(widths)

    @staticmethod
    def _resolve_key_column(raw: object, columns: tuple[str, ...]) -> int:
        """Resolve a wire key-column (index or name) to a column index.

        A name is resolved to its index; a name absent from ``columns`` is a wire
        error naming the offending name (never a silent ``-1``). An int is kept
        as-is so ``validate`` reports an out-of-range index against the agent's
        own value. A non-int, non-str value is a wire type error.
        """
        if isinstance(raw, bool) or not isinstance(raw, int | str):
            got = type(raw).__name__
            msg = f"key_column must be an int or a column name, got {got}"
            raise ValueError(msg)
        if isinstance(raw, int):
            return raw
        if raw not in columns:
            msg = f"key_column {raw!r} does not name a column ({list(columns)})"
            raise ValueError(msg)
        return columns.index(raw)

    @staticmethod
    def _decode_mode(raw: Mapping[str, object]) -> SelectionMode:
        """Decode the selection mode, defaulting to ``none``."""
        value = raw.get("selection_mode", "none")
        if value not in _SELECTION_MODES:
            modes = sorted(_SELECTION_MODES)
            msg = f"selection_mode must be one of {modes}, got {value!r}"
            raise ValueError(msg)
        return cast("SelectionMode", value)

    @staticmethod
    def _decode_selected_ids(
        ctx: ElementWireContext, raw: Mapping[str, object]
    ) -> list[str]:
        """Decode the selected row ids, ``[]`` when absent."""
        if "selected_row_ids" not in raw:
            return []
        return ctx.optional_string_list(raw, "selected_row_ids")

    def _install_handlers(self, elem: TableElement, raw: Mapping[str, object]) -> None:
        """Install row-selection handlers declared by the wire ``handlers`` list."""
        handlers_raw = raw.get("handlers")
        if handlers_raw is None:
            return
        if not isinstance(handlers_raw, list):
            msg = f"table 'handlers' must be a list, got {type(handlers_raw).__name__}"
            raise TypeError(msg)
        for i, spec in enumerate(cast("list[object]", handlers_raw)):
            if not isinstance(spec, dict):
                got = type(spec).__name__
                msg = f"table 'handlers[{i}]' must be a mapping, got {got}"
                raise TypeError(msg)
            spec_map = cast("Mapping[str, object]", spec)
            event_type = self._resolve_event_type(spec_map, i)
            handler = self._handler_decoder.decode_spec(spec_map)
            elem.add_handler(event_type, handler)

    @staticmethod
    def _resolve_event_type(
        spec: Mapping[str, object], index: int
    ) -> type[RowSelectionChanged]:
        """Map the wire ``event`` string to its typed event class."""
        event_name = spec.get("event")
        if not isinstance(event_name, str) or not event_name:
            msg = (
                f"table 'handlers[{index}]' requires an 'event' string, "
                f"got {event_name!r}"
            )
            raise ValueError(msg)
        event_type = _ROW_EVENT_TYPES.get(event_name)
        if event_type is None:
            known = sorted(_ROW_EVENT_TYPES)
            msg = (
                f"table 'handlers[{index}].event' = {event_name!r} is not "
                f"recognised (expected one of {known})"
            )
            raise ValueError(msg)
        return event_type


class JsonTableEncoder:
    """Encode an ABC ``TableElement`` to its JSON-compatible wire dict.

    Stateless. Emits the always-present grid fields and only the selection fields
    that differ from the display-only defaults, so a basic grid stays terse.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode(self, elem: TableElement) -> dict[str, object]:
        """Serialize a TableElement to a JSON-compatible dict."""
        payload: dict[str, object] = {
            "kind": "table",
            "id": elem.id,
            "columns": list(elem.columns),
            "rows": [list(row) for row in elem.rows],
            "flags": elem.flags.to_wire(),
            "key_column": elem.key_column,
        }
        if elem.column_widths:
            payload["column_widths"] = list(elem.column_widths)
        if elem.selection_mode != "none":
            payload["selection_mode"] = elem.selection_mode
        if elem.selected_row_ids:
            payload["selected_row_ids"] = sorted(elem.selected_row_ids)
        if elem.anchor_row_id:
            payload["anchor_row_id"] = elem.anchor_row_id
        if elem.tooltip is not None:
            payload["tooltip"] = elem.tooltip
        if elem.scroll_reserve_lines:
            payload["scroll_reserve_lines"] = elem.scroll_reserve_lines
        return payload


def decode_table_from_dict(
    cls: type[TableElement], d: Mapping[str, object]
) -> TableElement:
    """Decode a standalone TableElement (``TableElement.from_dict``'s body).

    Wires a noop-only handler decoder so a table with no wire ``handlers`` decodes
    without a real publish bus; a spec whose decorator chain invokes ``publish``
    raises via ``RaisingPublishSink``. Kept here, beside the decoder, so the
    element's ``from_dict`` stays a one-line Protocol-satisfying delegator.
    """
    decoder = JsonTableDecoder(
        renderer_factory=RAISING_FACTORY,
        emit=NO_EMIT,
        element_cls=cls,
        handler_decoder=build_standalone_row_selection_handler_decoder(
            cast("PublishSink", RaisingPublishSink("TableElement.from_dict")),
        ),
    )
    return decoder.decode(d)
