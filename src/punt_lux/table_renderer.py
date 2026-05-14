"""Table element rendering — filters, pagination, row selection, detail panel."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, Self

from punt_lux.protocol import InteractionMessage, TableDetail, TableElement, TableFilter
from punt_lux.widget_state import WidgetState

if TYPE_CHECKING:
    from punt_lux.types import EmitEventFn

logger = logging.getLogger(__name__)

# Type alias: (original_row_index, row_data)
IndexedRow = tuple[int, list[Any]]

_ROWS_PER_PAGE = 10


class TableRenderer:
    """Render table elements — filters, pagination, row selection, detail panel."""

    _widget_state: WidgetState
    _emit_event: EmitEventFn

    def __new__(
        cls,
        widget_state: WidgetState,
        emit_event: EmitEventFn,
    ) -> Self:
        self = super().__new__(cls)
        self._widget_state = widget_state
        self._emit_event = emit_event
        return self

    @property
    def widget_state(self) -> WidgetState:
        return self._widget_state

    @widget_state.setter
    def widget_state(self, value: WidgetState) -> None:
        self._widget_state = value

    # -- public entry point ----------------------------------------------------

    def render(self, table: TableElement, scene_id: str) -> None:
        """Render a complete table element with filters, pagination, and detail."""
        from imgui_bundle import imgui

        eid = table.id
        columns = table.columns
        rows = table.rows
        flags_list = table.flags
        filters = table.filters
        detail = table.detail
        has_detail = detail is not None

        num_cols = len(columns)
        if num_cols == 0:
            return

        # Render built-in filters and get visible rows with indices
        indexed_rows, filters_changed = self._apply_table_filters(
            filters,
            rows,
            eid,
            imgui,
        )

        table_flags, copy_id = self._parse_table_flags(flags_list, imgui)

        # Cache column weights -- recompute when rows object or widths change.
        # id(rows) changes on update() since _apply_patch_set creates a new list.
        weight_cache_key = f"__tbl_wcache_{eid}"
        cached = self._widget_state.get(weight_cache_key)
        rows_id = id(rows)
        cw_sig = tuple(table.column_widths) if table.column_widths else None
        if cached is not None and cached[0] == rows_id and cached[1] == cw_sig:
            weights = cached[2]
        else:
            weights = _table_column_weights(columns, rows, table.column_widths)
            self._widget_state.set(weight_cache_key, (rows_id, cw_sig, weights))

        imgui_id = f"##{scene_id}/{eid}"
        sel_key = f"__tbl_sel_{eid}"
        page_key = f"__tbl_page_{eid}"

        # Reset page to 0 when filters change
        if filters_changed:
            self._widget_state.set(page_key, 0)

        # Paginate -- slice visible rows to current page
        start, end, page_changed = self._render_table_pagination(
            len(indexed_rows),
            eid,
            page_key,
            imgui,
        )
        page_rows = indexed_rows[start:end]

        # Auto-select first row on initial load, page change, or filter change
        current_sel: int = self._widget_state.ensure(sel_key, -1)
        needs_auto_select = current_sel < 0 or page_changed or filters_changed
        if has_detail and needs_auto_select and page_rows:
            first_orig = page_rows[0][0]
            self._widget_state.set(sel_key, first_orig)
        # Track prev_sel AFTER auto-select so auto-select doesn't trigger copy
        prev_sel: int = self._widget_state.ensure(sel_key, -1)

        if imgui.begin_table(imgui_id, num_cols, table_flags):
            stretch = imgui.TableColumnFlags_.width_stretch.value
            for col_idx, col_name in enumerate(columns):
                imgui.table_setup_column(col_name, stretch, weights[col_idx])
            imgui.table_headers_row()

            selected_orig, row_clicked = self._render_table_rows(
                page_rows,
                num_cols,
                selectable=has_detail or copy_id,
                table_id=eid,
                sel_key=sel_key,
                imgui=imgui,
            )
            imgui.end_table()

        else:
            selected_orig = self._widget_state.ensure(sel_key, -1)
            row_clicked = False

        # Keyboard navigation -- up/down arrows move selection
        if has_detail:
            selected_orig = self._handle_table_keyboard_nav(
                page_rows,
                selected_orig,
                sel_key,
                imgui,
            )

        # Copy first column to clipboard on user-initiated selection
        _maybe_copy_id(
            copy_id=copy_id,
            selected_orig=selected_orig,
            prev_sel=prev_sel,
            row_clicked=row_clicked,
            rows=rows,
            imgui=imgui,
        )

        # Emit row_select event on user-initiated click
        if row_clicked and 0 <= selected_orig < len(rows):
            self._emit_event(
                InteractionMessage(
                    element_id=eid,
                    action="row_select",
                    ts=time.time(),
                    value={
                        "row_index": selected_orig,
                        "row": rows[selected_orig],
                    },
                )
            )

        if detail is not None and selected_orig >= 0:
            tbl_row = rows[selected_orig] if selected_orig < len(rows) else None
            _render_table_detail(
                detail,
                selected_orig,
                eid,
                imgui,
                table_row=tbl_row,
            )

    # -- filter rendering ------------------------------------------------------

    def _render_filter_search(
        self,
        filt: TableFilter,
        f_idx: int,
        table_id: str,
        imgui: Any,
    ) -> None:
        """Render a search input for a table filter."""
        sid = f"__tbl_search_{f_idx}_{table_id}"
        current: str = self._widget_state.ensure(sid, "")
        label = filt.label or "Search"
        imgui.set_next_item_width(180)
        hint: str = filt.hint or ""
        if hint:
            changed, new_val = imgui.input_text_with_hint(
                f"{label}##{sid}",
                hint,
                current,
                256,
            )
        else:
            changed, new_val = imgui.input_text(
                f"{label}##{sid}",
                current,
                256,
            )
        if changed:
            self._widget_state.set(sid, new_val)

    def _render_filter_combo(
        self,
        filt: TableFilter,
        f_idx: int,
        table_id: str,
        imgui: Any,
    ) -> None:
        """Render a combo dropdown for a table filter."""
        sid = f"__tbl_combo_{f_idx}_{table_id}"
        items: list[str] = filt.items or []
        if not items:
            return
        current_idx: int = self._widget_state.ensure(sid, 0)
        # Clamp index to valid range (items may change via update())
        if current_idx < 0 or current_idx >= len(items):
            current_idx = 0
            self._widget_state.set(sid, 0)
        label = filt.label or "Filter"
        imgui.set_next_item_width(140)
        changed, new_idx = imgui.combo(
            f"{label}##{sid}",
            current_idx,
            items,
        )
        if changed:
            self._widget_state.set(sid, new_idx)

    def _apply_table_filters(
        self,
        filters: list[TableFilter] | None,
        rows: list[list[Any]],
        table_id: str,
        imgui: Any,
    ) -> tuple[list[IndexedRow], bool]:
        """Render built-in filter controls and return matching rows with indices.

        Returns ``(indexed_rows, filters_changed)`` -- the bool is True when
        filter state changed this frame (for auto-selecting the first row).
        """
        indexed: list[IndexedRow] = list(enumerate(rows))
        if not filters:
            return indexed, False

        # Snapshot filter state before rendering (widgets may update state)
        snap_key = f"__tbl_fsnap_{table_id}"
        prev_snap: str = self._widget_state.get(snap_key, "")

        for f_idx, filt in enumerate(filters):
            if f_idx > 0:
                imgui.same_line()
            if filt.type == "search":
                self._render_filter_search(filt, f_idx, table_id, imgui)
            elif filt.type == "combo":
                self._render_filter_combo(filt, f_idx, table_id, imgui)

        # Detect filter changes
        curr_snap = _get_filter_snapshot(filters, table_id, self._widget_state)
        # Treat initial snapshot (prev_snap == "") as a change so pagination
        # resets and first row auto-selects when filters are first introduced.
        filters_changed = curr_snap != prev_snap
        self._widget_state.set(snap_key, curr_snap)

        visible = _filter_indexed_rows(filters, indexed, table_id, self._widget_state)
        total = len(rows)
        shown = len(visible)
        if shown < total:
            imgui.text_disabled(f"Showing {shown} of {total}")
        else:
            imgui.text_disabled(f"{total} rows")

        return visible, filters_changed

    # -- pagination ------------------------------------------------------------

    def _render_table_pagination(
        self,
        total_rows: int,
        table_id: str,
        page_key: str,
        imgui: Any,
    ) -> tuple[int, int, bool]:
        """Render pagination controls and return (start, end, page_changed)."""
        if total_rows <= _ROWS_PER_PAGE:
            return 0, total_rows, False

        page: int = self._widget_state.ensure(page_key, 0)
        total_pages = (total_rows + _ROWS_PER_PAGE - 1) // _ROWS_PER_PAGE
        clamped = max(0, min(page, total_pages - 1))
        # Persist clamped value (e.g. after rows shrink from update/filter)
        if clamped != page:
            self._widget_state.set(page_key, clamped)
        page = clamped
        prev_page = page

        if imgui.button(f"<< Prev##{table_id}_prev") and page > 0:
            page -= 1
        imgui.same_line()
        imgui.text(f"Page {page + 1} of {total_pages}")
        imgui.same_line()
        if imgui.button(f"Next >>##{table_id}_next") and page < total_pages - 1:
            page += 1

        page_changed = page != prev_page
        if page_changed:
            self._widget_state.set(page_key, page)

        start = page * _ROWS_PER_PAGE
        end = min(start + _ROWS_PER_PAGE, total_rows)
        return start, end, page_changed

    # -- row rendering ---------------------------------------------------------

    def _render_table_rows(
        self,
        indexed_rows: list[IndexedRow],
        num_cols: int,
        *,
        selectable: bool,
        table_id: str,
        sel_key: str,
        imgui: Any,
    ) -> tuple[int, bool]:
        """Render table body rows with optional row selection.

        Returns ``(selected_orig, row_clicked)``.
        """
        selected_orig: int = self._widget_state.ensure(sel_key, -1)
        row_clicked = False
        for orig_idx, row in indexed_rows:
            imgui.table_next_row()
            for col_idx, cell in enumerate(row):
                if col_idx >= num_cols:
                    continue
                imgui.table_set_column_index(col_idx)
                if col_idx == 0 and selectable:
                    is_sel = orig_idx == selected_orig
                    flags = imgui.SelectableFlags_.span_all_columns.value
                    clicked, _ = imgui.selectable(
                        f"{cell}##{table_id}_{orig_idx}",
                        is_sel,
                        flags,
                    )
                    if clicked:
                        self._widget_state.set(sel_key, orig_idx)
                        selected_orig = orig_idx
                        row_clicked = True
                else:
                    imgui.text_wrapped(str(cell))
        return selected_orig, row_clicked

    # -- keyboard navigation ---------------------------------------------------

    def _handle_table_keyboard_nav(
        self,
        indexed_rows: list[IndexedRow],
        selected_orig: int,
        sel_key: str,
        imgui: Any,
    ) -> int:
        """Handle up/down arrow keyboard navigation for selectable table rows."""
        if not indexed_rows or selected_orig < 0:
            return selected_orig

        orig_indices = [orig_idx for orig_idx, _ in indexed_rows]
        if selected_orig not in orig_indices:
            return selected_orig

        cur_pos = orig_indices.index(selected_orig)

        if imgui.is_key_pressed(imgui.Key.up_arrow) and cur_pos > 0:
            new_orig = orig_indices[cur_pos - 1]
            self._widget_state.set(sel_key, new_orig)
            return new_orig

        is_down = imgui.is_key_pressed(imgui.Key.down_arrow)
        if is_down and cur_pos < len(orig_indices) - 1:
            new_orig = orig_indices[cur_pos + 1]
            self._widget_state.set(sel_key, new_orig)
            return new_orig

        return selected_orig

    # -- flag parsing ----------------------------------------------------------

    @staticmethod
    def _parse_table_flags(
        flags_list: list[str],
        imgui: Any,
    ) -> tuple[int, bool]:
        """Parse Lux table flags into imgui flags and Lux-level booleans.

        Returns ``(imgui_flags, copy_id)``.
        """
        flag_map = {
            "borders": imgui.TableFlags_.borders.value,
            "row_bg": imgui.TableFlags_.row_bg.value,
            "resizable": imgui.TableFlags_.resizable.value,
            "sortable": imgui.TableFlags_.sortable.value,
        }
        imgui_flags = 0
        copy_id = False
        for f in flags_list:
            if f == "copy_id":
                copy_id = True
            else:
                imgui_flags |= flag_map.get(f, 0)
        return imgui_flags, copy_id


# -- pure functions (no imgui dependency) --------------------------------------


def _get_filter_snapshot(
    filters: list[TableFilter],
    table_id: str,
    widget_state: WidgetState,
) -> str:
    """Return a string snapshot of current filter state for change detection."""
    parts: list[str] = []
    for f_idx, filt in enumerate(filters):
        if filt.type == "search":
            sid = f"__tbl_search_{f_idx}_{table_id}"
            parts.append(widget_state.get(sid, ""))
        elif filt.type == "combo":
            sid = f"__tbl_combo_{f_idx}_{table_id}"
            parts.append(str(widget_state.get(sid, 0)))
    return "\x00".join(parts)


def _filter_indexed_rows(
    filters: list[TableFilter],
    rows: list[IndexedRow],
    table_id: str,
    widget_state: WidgetState,
) -> list[IndexedRow]:
    """Apply all active filters to indexed rows with AND logic."""
    result = rows
    for f_idx, filt in enumerate(filters):
        ftype: str = filt.type
        if ftype == "search":
            sid = f"__tbl_search_{f_idx}_{table_id}"
            query: str = widget_state.get(sid, "")
            if not query:
                continue
            query_lower = query.lower()
            cols: list[int] = filt.column
            result = [
                ir
                for ir in result
                if any(
                    query_lower in str(ir[1][c]).lower()
                    for c in cols
                    if 0 <= c < len(ir[1])
                )
            ]
        elif ftype == "combo":
            result = _filter_combo(filt, f_idx, table_id, widget_state, result)
        else:
            logger.warning("Unknown filter type %r in table %s", ftype, table_id)
    return result


def _filter_combo(
    filt: TableFilter,
    f_idx: int,
    table_id: str,
    widget_state: WidgetState,
    rows: list[IndexedRow],
) -> list[IndexedRow]:
    """Apply a single combo filter to indexed rows."""
    sid = f"__tbl_combo_{f_idx}_{table_id}"
    selected_idx: int = widget_state.get(sid, 0)
    items: list[str] = filt.items or []
    if not items or selected_idx == 0:
        return rows
    # Reset stale index (e.g. items changed via update()) to "All"
    if selected_idx < 0 or selected_idx >= len(items):
        widget_state.set(sid, 0)
        return rows
    selected_val = items[selected_idx]
    if not filt.column:
        return rows
    col_idx: int = filt.column[0]
    return [
        ir
        for ir in rows
        if 0 <= col_idx < len(ir[1]) and str(ir[1][col_idx]) == selected_val
    ]


def _table_column_weights(
    columns: list[str],
    rows: list[list[Any]],
    explicit: list[float] | None,
) -> list[float]:
    """Compute proportional column weights for ImGui table_setup_column.

    Uses explicit weights when provided, otherwise auto-sizes by scanning
    max cell string length per column.
    """
    num_cols = len(columns)
    if explicit is not None:
        if len(explicit) == num_cols:
            return explicit
        logger.warning(
            "Ignoring explicit column weights: have %d columns but %d weights",
            num_cols,
            len(explicit),
        )
    weights = [float(len(col)) for col in columns]
    for row in rows:
        for col_idx, cell in enumerate(row):
            if col_idx < num_cols:
                weights[col_idx] = max(weights[col_idx], float(len(str(cell))))
    # Floor at 4.0 so short columns (e.g. "P2") don't collapse to
    # near-zero when stretched beside long-content columns.
    return [max(w, 4.0) for w in weights]


def _maybe_copy_id(
    *,
    copy_id: bool,
    selected_orig: int,
    prev_sel: int,
    row_clicked: bool,
    rows: list[list[Any]],
    imgui: Any,
) -> None:
    """Copy first column to clipboard on user-initiated row selection.

    Triggers on selection change (keyboard or click) OR explicit
    same-row re-click.  Uses the ``row_clicked`` signal from
    ``_render_table_rows`` to avoid false positives from clicks on
    filter controls, scrollbars, or other non-row widgets.
    """
    if not copy_id or not (0 <= selected_orig < len(rows)):
        return
    changed = selected_orig != prev_sel
    if changed or row_clicked:
        imgui.set_clipboard_text(str(rows[selected_orig][0]))


def _render_table_detail(
    detail: TableDetail,
    row_idx: int,
    table_id: str,
    imgui: Any,
    *,
    table_row: list[Any] | None = None,
) -> None:
    """Render the detail panel for a selected table row."""
    fields: list[str] = detail.fields
    detail_rows: list[list[Any]] = detail.rows
    body_list: list[str] = detail.body

    if row_idx >= min(len(detail_rows), len(body_list)):
        return

    row_data = detail_rows[row_idx]
    body = body_list[row_idx]

    imgui.separator()

    # Scrollable child region -- takes all remaining height
    avail = imgui.get_content_region_avail()
    child_h = max(avail.y, 100.0)
    child_id = f"__tbl_detail__{table_id}"
    if imgui.begin_child(child_id, imgui.ImVec2(0, child_h)):
        # Banner heading from table row (ID: Title) or detail row fallback
        heading_src = table_row if table_row else row_data
        if heading_src:
            heading = str(heading_src[0])
            if len(heading_src) > 1:
                heading = f"{heading_src[0]}: {heading_src[1]}"
            imgui.separator_text(heading)

        # 2-column metadata grid
        _render_detail_field_grid(fields, row_data, table_id, imgui)

        if body:
            imgui.separator()
            imgui.text_wrapped(body)

    imgui.end_child()


def _render_detail_field_grid(
    fields: list[str],
    values: list[Any],
    table_id: str,
    imgui: Any,
) -> None:
    """Render fields as a 2-column grid: Field | Value | Field | Value."""
    n = min(len(fields), len(values))
    if n == 0:
        return

    grid_id = f"__tbl_fgrid__{table_id}"
    tflags = imgui.TableFlags_.borders.value
    if imgui.begin_table(grid_id, 4, tflags):
        stretch = imgui.TableColumnFlags_.width_stretch.value
        imgui.table_setup_column("Field", stretch, 1.0)
        imgui.table_setup_column("Value", stretch, 2.0)
        imgui.table_setup_column("Field", stretch, 1.0)
        imgui.table_setup_column("Value", stretch, 2.0)

        # Pair fields: (0,1), (2,3), (4,5), ...
        for i in range(0, n, 2):
            imgui.table_next_row()
            # Left pair
            imgui.table_set_column_index(0)
            imgui.text(fields[i])
            imgui.table_set_column_index(1)
            imgui.text(str(values[i]))
            # Right pair (if exists)
            if i + 1 < n:
                imgui.table_set_column_index(2)
                imgui.text(fields[i + 1])
                imgui.table_set_column_index(3)
                imgui.text(str(values[i + 1]))

        imgui.end_table()
