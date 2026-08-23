"""TableElement — the basic data grid on the Element ABC.

A ``tree``-shaped data leaf (its rows are data, not child elements) that is also
``checkbox``-interactive: it owns a Hub-authoritative row selection set, and a
user gesture fires ``RowSelectionChanged`` down the D21 path. The selection names
stable ``row_id``s (a row's ``key_column`` value), reconciled by set intersection
when the rows change, so survivors keep their ids across a reorder (DES-045).

The chrome the legacy table carried — a filter bar, search box, status combos, a
detail panel — is *not* here; those are compositions of ``input_text`` / ``combo``
/ ``group`` primitives wired through the D21 handler path (see the show_table
composition). This element is columns, rows, a key column, a selection, render
flags, and optional column widths.

The codec body lives in ``table_codec.py``; ``to_dict`` / ``from_dict`` stay here
as short delegators so the runtime-checkable ``domain.element.Element`` Protocol
stays satisfied (PY-OO-2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, cast

from punt_lux.domain.element_abc import Element
from punt_lux.domain.remote_dispatch_spec import RemoteDispatchSpec
from punt_lux.domain.selection_interaction import RowSelectionChanged
from punt_lux.domain.validation import ValidationError
from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.patch_field import PatchField
from punt_lux.protocol.elements.table_codec import (
    JsonTableEncoder,
    decode_table_from_dict,
)
from punt_lux.protocol.elements.table_flags import TableFlags
from punt_lux.protocol.elements.table_selection_model import (
    SelectionMode,
    TableSelectionModel,
)
from punt_lux.protocol.elements.table_validation import TableValidator
from punt_lux.protocol.elements.table_wire import TableWire

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["TableElement"]

_DEFAULT_FLAGS = TableFlags()


class TableElement(Element):
    """A basic data grid: a data leaf with a Hub-authoritative row selection.

    ``tooltip`` stays ``str | None`` — absence is the documented contract for an
    optional tooltip (PY-TS-14). ``column_widths`` is ``()`` when the grid
    auto-sizes; ``key_column`` is the resolved column index (a wire name is
    resolved to its index at decode).
    """

    _id: str
    _columns: tuple[str, ...]
    _rows: tuple[tuple[object, ...], ...]
    _flags: TableFlags
    _column_widths: tuple[float, ...]
    _key_column: int
    _selection: TableSelectionModel
    _tooltip: str | None
    _scroll_reserve_lines: int
    _kind: Literal["table"]
    _live_ids_cache: frozenset[str]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory = RAISING_FACTORY,
        emit: Emit = NO_EMIT,
        id: str,
        columns: Iterable[str] = (),
        rows: Iterable[Iterable[object]] = (),
        flags: TableFlags = _DEFAULT_FLAGS,
        column_widths: Iterable[float] = (),
        key_column: int = 0,
        selection_mode: SelectionMode = "none",
        selected_row_ids: frozenset[str] = frozenset(),
        anchor_row_id: str = "",
        tooltip: str | None = None,
        scroll_reserve_lines: int = 0,
    ) -> Self:
        # Columns/rows coerce to tuples: callers pass lists, storage stays immutable.
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._columns = tuple(columns)
        self._rows = tuple(tuple(row) for row in rows)
        self._flags = flags
        self._column_widths = tuple(column_widths)
        self._key_column = key_column
        self._selection = TableSelectionModel(
            mode=selection_mode, selected=selected_row_ids, anchor=anchor_row_id
        )
        self._tooltip = tooltip
        self._scroll_reserve_lines = scroll_reserve_lines
        self._kind = "table"
        self._live_ids_cache = self._compute_live_ids()
        return self

    # -- read-only accessors (the wire-facing surface) ----------------------

    @property
    def id(self) -> str:
        """Return the table's stable identity within its enclosing Scene."""
        return self._id

    @property
    def kind(self) -> Literal["table"]:
        """Return the wire discriminator — always ``"table"``."""
        return self._kind

    @property
    def columns(self) -> tuple[str, ...]:
        """Return the column headers (read-only)."""
        return self._columns

    @property
    def rows(self) -> tuple[tuple[object, ...], ...]:
        """Return the row data (read-only), each row a tuple of scalar cells."""
        return self._rows

    @property
    def flags(self) -> TableFlags:
        """Return the grid render flags (borders, sortable, …)."""
        return self._flags

    @property
    def column_widths(self) -> tuple[float, ...]:
        """Return explicit column weights, or ``()`` to auto-size."""
        return self._column_widths

    @property
    def key_column(self) -> int:
        """Return the resolved key-column index (the row-id source)."""
        return self._key_column

    @property
    def selection_mode(self) -> SelectionMode:
        """Return the selection mode (``none`` / ``single`` / ``multi``)."""
        return self._selection.mode

    @property
    def selected_row_ids(self) -> frozenset[str]:
        """Return the Hub-authoritative selected row ids (the visible set)."""
        return self._selection.selected_row_ids

    @property
    def anchor_row_id(self) -> str:
        """Return the last-interacted row's id (a detail sibling binds to it)."""
        return self._selection.anchor

    @property
    def tooltip(self) -> str | None:
        """Return the hover-tooltip text, or ``None`` for no tooltip."""
        return self._tooltip

    @property
    def scroll_reserve_lines(self) -> int:
        """Return the text lines to leave below the scroll region for a sibling.

        Nonzero for a composed table with a detail panel, so the grid's scroll
        region stops short and the panel stays visible; ``0`` uses full height.
        """
        return self._scroll_reserve_lines

    # -- row identity -------------------------------------------------------

    def row_id(self, row: tuple[object, ...]) -> str:
        """Return ``row``'s stable id — its key-column cell as a string.

        Guarded so a ragged row (shorter than the key column) yields ``""``
        rather than an ``IndexError``; ``validate`` reports the raggedness.
        """
        if 0 <= self._key_column < len(row):
            return str(row[self._key_column])
        return ""

    def _compute_live_ids(self) -> frozenset[str]:
        """Scan the rows for ``_live_ids_cache`` (never on a selection-only patch)."""
        return frozenset(self.row_id(row) for row in self._rows)

    # -- minimal setters for the scene patch path --------------------------

    def _set_rows(self, value: object) -> None:
        """Replace the rows and reconcile the selection to the live ids.

        Notifies ``rows`` so a bound ``FilteredTableModel`` can absorb an external
        (agent) dataset refresh; and, when the reconcile drops a now-absent row
        from the selection or reseats the anchor, ``selected_row_ids`` so the same
        model and a bound detail re-drive instead of going stale until the next
        selection write. Both notifications are deferred to patch commit like any
        other, so atomicity holds.
        """
        self._rows = TableWire.rows_from_wire(value)
        self._live_ids_cache = self._compute_live_ids()
        before = self._selection
        self._selection = self._selection.reconciled(self._live_ids_cache)
        self._notify_observers("rows")
        if (
            self._selection.selected_row_ids != before.selected_row_ids
            or self._selection.anchor != before.anchor
        ):
            self._notify_observers("selected_row_ids")

    def _set_columns(self, value: object) -> None:
        """Replace the column headers."""
        self._columns = TableWire.columns_from_wire(value)

    def _set_flags(self, value: object) -> None:
        """Replace the render flags from a wire name list."""
        self._flags = TableFlags.from_wire(TableWire.str_list(value, "flags"))

    def _set_selected_row_ids(self, value: object) -> None:
        """Replace the selection from an agent drive or the built-in handler.

        The ids are intersected with the live rows so a selection racing a rows
        re-push never lands a ghost id in the authoritative set (which the
        renderer would then read back as a spurious per-frame user change).

        Observers are notified so a filtered composition's ``FilteredTableModel``
        folds the write into its full selection — an agent ``apply_patch`` reaches
        the model the same way a gesture does, instead of being shadowed on the
        next re-projection.
        """
        wire_ids = TableWire.str_list(value, "selected_row_ids")
        ids = frozenset(wire_ids) & self._live_ids_cache
        self._selection = self._selection.with_selection(ids)
        self._notify_observers("selected_row_ids")

    def _set_anchor_row_id(self, value: object) -> None:
        """Set the anchor (a detail sibling shows it) and notify, so an anchor-only
        patch re-drives a bound detail (deferred + de-duped like the other setters)."""
        self._selection = self._selection.with_anchor(
            PatchField("anchor_row_id").as_str(value)
        )
        self._notify_observers("selected_row_ids")

    def _set_tooltip(self, value: object) -> None:
        """Replace the tooltip text."""
        self._tooltip = PatchField("tooltip").as_optional_str(value)

    def _remote_dispatch_specs(self) -> tuple[RemoteDispatchSpec, ...]:
        """Return the row-selection dispatch spec — none for a display-only grid.

        A ``none``-mode grid advertises none, so introspection reports it as
        non-interactive and the Display wraps no handler for it.
        """
        if self.selection_mode == "none":
            return ()
        return (
            RemoteDispatchSpec(RowSelectionChanged, self.id, "row_selection_changed"),
        )

    # -- self-validation ---------------------------------------------------

    def validate(self) -> tuple[ValidationError, ...]:
        """Return errors where the data or selection does not fit the grid.

        Delegated to ``TableValidator``: rows-vs-columns shape and renderable
        cells always; the key column, its values, and the selection when selectable.
        """
        return TableValidator(self).errors()

    # -- codec delegators ---------------------------------------------------

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonTableEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        """Construct a TableElement from a JSON-decoded mapping.

        The decoder wiring (a noop-only handler decoder so a table with no
        ``handlers`` decodes without a publish bus) lives in ``table_codec`` so
        this stays a one-line delegator satisfying the ``Element`` Protocol.
        """
        return cast("Self", decode_table_from_dict(cls, d))

    # -- introspection (Inspectable) ---------------------------------------

    def resolved_props(self) -> Mapping[str, object]:
        """Return the full resolved state, including the selection view-state."""
        return {
            "columns": list(self._columns),
            "row_count": len(self._rows),
            "flags": self._flags.to_wire(),
            "key_column": self._key_column,
            "selection_mode": self._selection.mode,
            "selected_row_ids": sorted(self._selection.selected_row_ids),
            "anchor_row_id": self._selection.anchor,
            "tooltip": self._tooltip,
            "scroll_reserve_lines": self._scroll_reserve_lines,
        }
