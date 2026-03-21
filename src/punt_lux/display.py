# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportMissingModuleSource=false
"""Lux display server — ImGui render loop with non-blocking Unix socket IPC.

Listens on a Unix domain socket for protocol messages and renders scenes
using imgui-bundle. Socket I/O is polled every frame via ``select()`` with
zero timeout — no threads, no asyncio.

This module imports numpy and Pillow at module level but defers ImGui and
OpenGL imports to method bodies. It can be imported by unit tests (for state
machine testing) but ``run()`` requires a GPU-capable environment.
"""

from __future__ import annotations

import contextlib
import logging
import platform
import select
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Literal, cast

import numpy as np
from PIL import Image

from punt_lux.paths import (
    cleanup_stale_socket,
    default_socket_path,
    remove_pid_file,
    write_pid_file,
)
from punt_lux.protocol import (
    HEADER_SIZE,
    MAX_MESSAGE_SIZE,
    AckMessage,
    CheckboxElement,
    ClearMessage,
    CollapsingHeaderElement,
    ColorPickerElement,
    ComboElement,
    ConnectMessage,
    FrameReader,
    GroupElement,
    InputTextElement,
    InteractionMessage,
    MenuMessage,
    PingMessage,
    PongMessage,
    RadioElement,
    ReadyMessage,
    RegisterMenuMessage,
    SceneMessage,
    SelectableElement,
    SliderElement,
    TabBarElement,
    ThemeMessage,
    UnknownMessage,
    UpdateMessage,
    WindowElement,
    encode_message,
)

if TYPE_CHECKING:
    from punt_lux.protocol import Element, Message

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Texture cache
# ---------------------------------------------------------------------------


class TextureCache:
    """Maps file paths to OpenGL texture IDs. Uploads on first access."""

    def __init__(self) -> None:
        self._textures: dict[str, int] = {}

    def get_or_load(self, path: str) -> int | None:
        """Return a texture ID for *path*, uploading if needed."""
        if path in self._textures:
            return self._textures[path]
        if not Path(path).is_file():
            logger.warning("Image file not found: %s", path)
            return None
        tex_id = _create_texture(path)
        if tex_id is not None:
            self._textures[path] = tex_id
        return tex_id

    def cleanup(self) -> None:
        """Delete all OpenGL textures."""
        import OpenGL.GL as GL

        for tex_id in self._textures.values():
            GL.glDeleteTextures(1, [tex_id])
        self._textures.clear()


def _create_texture(path: str) -> int | None:
    """Load an image file and upload it as an OpenGL texture."""
    import OpenGL.GL as GL

    try:
        img = Image.open(path).convert("RGBA")
    except Exception:
        logger.exception("Failed to load image: %s", path)
        return None

    data = np.array(img, dtype=np.uint8)
    h, w = data.shape[:2]

    tex_id: int = GL.glGenTextures(1)
    GL.glBindTexture(GL.GL_TEXTURE_2D, tex_id)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR)
    GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
    GL.glTexImage2D(
        GL.GL_TEXTURE_2D,
        0,
        GL.GL_RGBA,
        w,
        h,
        0,
        GL.GL_RGBA,
        GL.GL_UNSIGNED_BYTE,
        data,
    )
    GL.glBindTexture(GL.GL_TEXTURE_2D, 0)
    return int(tex_id)


# ---------------------------------------------------------------------------
# Widget state (persistent across ImGui frames)
# ---------------------------------------------------------------------------


class WidgetState:
    """Key-value store for interactive widget state across ImGui frames."""

    def __init__(self) -> None:
        self._state: dict[str, Any] = {}

    def get(self, element_id: str, default: Any = None) -> Any:
        return self._state.get(element_id, default)

    def set(self, element_id: str, value: Any) -> None:
        self._state[element_id] = value

    def ensure(self, element_id: str, default: Any) -> Any:
        if element_id not in self._state:
            self._state[element_id] = default
        return self._state[element_id]

    def clear(self) -> None:
        self._state.clear()

    def clear_suffix(self, suffix: str) -> None:
        """Remove all keys ending with *suffix*."""
        keys = [k for k in self._state if k.endswith(suffix)]
        for k in keys:
            del self._state[k]


# ---------------------------------------------------------------------------
# Color conversion helpers
# ---------------------------------------------------------------------------


def _parse_color(
    color: str | list[int] | tuple[int, ...] | Any,
) -> tuple[int, int, int, int]:
    """Parse a color value to (r, g, b, a) ints 0-255.

    Accepts hex strings (``"#RRGGBB"``, ``"#RRGGBBAA"``) or RGBA
    lists/tuples (``[r, g, b]``, ``[r, g, b, a]``, or longer —
    extra components beyond the fourth are ignored).
    """
    if isinstance(color, (list, tuple)):
        try:
            if len(color) >= 4:
                return (int(color[0]), int(color[1]), int(color[2]), int(color[3]))
            if len(color) == 3:
                return (int(color[0]), int(color[1]), int(color[2]), 255)
        except (TypeError, ValueError):
            pass
        logger.warning("Invalid RGBA color %r; using fallback white", color)
        return (255, 255, 255, 255)
    if not isinstance(color, str):
        logger.warning("Invalid color type %r; using fallback white", type(color))
        return (255, 255, 255, 255)
    h = color.lstrip("#")
    try:
        if len(h) == 6:
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return (r, g, b, 255)
        if len(h) == 8:
            r, g, b, a = (
                int(h[0:2], 16),
                int(h[2:4], 16),
                int(h[4:6], 16),
                int(h[6:8], 16),
            )
            return (r, g, b, a)
    except ValueError:
        logger.warning("Invalid hex color %r; using fallback white", color)
    return (255, 255, 255, 255)


def _color_to_hex(r: float, g: float, b: float) -> str:
    """Convert float RGB (0-1) to hex string."""
    ri = int(max(0.0, min(1.0, r)) * 255)
    gi = int(max(0.0, min(1.0, g)) * 255)
    bi = int(max(0.0, min(1.0, b)) * 255)
    return f"#{ri:02X}{gi:02X}{bi:02X}"


def _to_imgui_color(
    color: str | list[int] | tuple[int, ...] | Any,
) -> int:
    """Convert a color value to ImGui packed color (ImU32).

    Accepts hex strings or RGBA lists/tuples.
    """
    from imgui_bundle import ImVec4, imgui

    r, g, b, a = _parse_color(color)
    result: int = imgui.get_color_u32(
        ImVec4(r / 255.0, g / 255.0, b / 255.0, a / 255.0)
    )
    return result


def _widget_value(elem: Element) -> Any:
    """Extract the current widget value from an element for WidgetState."""
    if isinstance(elem, (SliderElement, CheckboxElement, InputTextElement)):
        return elem.value
    if isinstance(elem, SelectableElement):
        return elem.selected
    if isinstance(elem, (ComboElement, RadioElement)):
        return elem.selected
    if isinstance(elem, ColorPickerElement):
        r, g, b, _a = _parse_color(elem.value)
        from imgui_bundle import ImVec4

        return ImVec4(r / 255.0, g / 255.0, b / 255.0, 1.0)
    return None


# ---------------------------------------------------------------------------
# Recursive element tree helpers
# ---------------------------------------------------------------------------


def _get_children(elem: Element) -> list[list[Any]]:
    """Return all child lists owned by a container element."""
    if isinstance(elem, (GroupElement, CollapsingHeaderElement, WindowElement)):
        result: list[list[Any]] = [elem.children]
        if isinstance(elem, GroupElement) and elem.pages:
            result.extend(elem.pages)
        return result
    if isinstance(elem, TabBarElement):
        return [t.get("children", []) for t in elem.tabs]
    return []


def _draw_flame_shape(
    draw: Any,
    imgui: Any,
    base_x: float,
    base_y: float,
    tip_x: float,
    tip_y: float,
    width: float,
    height: float,
    *,
    r: float,
    g: float,
    b: float,
    alpha: float,
) -> None:
    """Draw a flame shape: rounded bulb at base tapering to a pointed tip.

    The shape is built from three bezier segments:
    1. Bottom arc: rounded base (semicircular)
    2. Left side: base-left up to tip (convex bulge then taper)
    3. Right side: tip back down to base-right (mirror)
    """
    from imgui_bundle import ImVec2

    color = imgui.get_color_u32((r, g, b, alpha))
    half_w = width

    bl = ImVec2(base_x - half_w, base_y)  # base left
    br = ImVec2(base_x + half_w, base_y)  # base right
    tip = ImVec2(tip_x, tip_y)

    # Kappa for circular arc approximation with cubic bezier
    kappa = 0.5522847498
    arc_cp = half_w * kappa  # horizontal control offset for bottom arc

    draw.path_clear()

    # Start at base-right, go clockwise
    draw.path_line_to(br)

    # Bottom arc: base-right → base-bottom → base-left (rounded base)
    base_bottom = ImVec2(base_x, base_y + half_w * 0.5)
    draw.path_bezier_cubic_curve_to(
        ImVec2(br.x, base_y + arc_cp * 0.5),  # cp1
        ImVec2(base_x + arc_cp, base_bottom.y),  # cp2
        base_bottom,
    )
    draw.path_bezier_cubic_curve_to(
        ImVec2(base_x - arc_cp, base_bottom.y),  # cp1
        ImVec2(bl.x, base_y + arc_cp * 0.5),  # cp2
        bl,
    )

    # Left side: base-left → tip (wide bulge then narrow taper)
    draw.path_bezier_cubic_curve_to(
        ImVec2(base_x - half_w * 1.3, base_y - height * 0.35),  # cp1: bulge out
        ImVec2(tip_x - width * 0.08, tip_y + height * 0.25),  # cp2: taper to tip
        tip,
    )

    # Right side: tip → base-right (mirror of left)
    draw.path_bezier_cubic_curve_to(
        ImVec2(tip_x + width * 0.08, tip_y + height * 0.25),  # cp1: taper from tip
        ImVec2(base_x + half_w * 1.3, base_y - height * 0.35),  # cp2: bulge out
        br,
    )

    draw.path_fill_convex(color)


def _collect_ids(elem: Element) -> list[str]:
    """Collect all element IDs in a subtree (including the root)."""
    ids: list[str] = []
    eid = getattr(elem, "id", None)
    if eid is not None:
        ids.append(eid)
    for child_list in _get_children(elem):
        for child in child_list:
            ids.extend(_collect_ids(child))
    return ids


def _find_element(
    elements: list[Element], target_id: str
) -> tuple[list[Element], int] | None:
    """Find element by id, returning (parent_list, index). Recurses into containers."""
    for i, e in enumerate(elements):
        if getattr(e, "id", None) == target_id:
            return (elements, i)
        for child_list in _get_children(e):
            result = _find_element(child_list, target_id)
            if result is not None:
                return result
    return None


def _render_filter_search(
    filt: Any,
    f_idx: int,
    table_id: str,
    widget_state: WidgetState,
    imgui: Any,
) -> None:
    """Render a search input for a table filter."""
    sid = f"__tbl_search_{f_idx}_{table_id}"
    current: str = widget_state.ensure(sid, "")
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
        widget_state.set(sid, new_val)


def _render_filter_combo(
    filt: Any,
    f_idx: int,
    table_id: str,
    widget_state: WidgetState,
    imgui: Any,
) -> None:
    """Render a combo dropdown for a table filter."""
    sid = f"__tbl_combo_{f_idx}_{table_id}"
    items: list[str] = filt.items or []
    if not items:
        return
    current_idx: int = widget_state.ensure(sid, 0)
    # Clamp index to valid range (items may change via update())
    if current_idx < 0 or current_idx >= len(items):
        current_idx = 0
        widget_state.set(sid, 0)
    label = filt.label or "Filter"
    imgui.set_next_item_width(140)
    changed, new_idx = imgui.combo(
        f"{label}##{sid}",
        current_idx,
        items,
    )
    if changed:
        widget_state.set(sid, new_idx)


# Type alias: (original_row_index, row_data)
IndexedRow = tuple[int, list[Any]]


def _get_filter_snapshot(
    filters: list[Any],
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


def _apply_table_filters(
    filters: list[Any] | None,
    rows: list[list[Any]],
    table_id: str,
    widget_state: WidgetState,
    imgui: Any,
) -> tuple[list[IndexedRow], bool]:
    """Render built-in filter controls and return matching rows with indices.

    Each filter's widget state is stored under an internal ID that won't
    collide with user element IDs (``__tbl_`` prefix).
    Returns ``(indexed_rows, filters_changed)`` — the bool is True when
    filter state changed this frame (for auto-selecting the first row).
    """
    indexed: list[IndexedRow] = list(enumerate(rows))
    if not filters:
        return indexed, False

    # Snapshot filter state before rendering (widgets may update state)
    snap_key = f"__tbl_fsnap_{table_id}"
    prev_snap: str = widget_state.get(snap_key, "")

    for f_idx, filt in enumerate(filters):
        if f_idx > 0:
            imgui.same_line()
        if filt.type == "search":
            _render_filter_search(filt, f_idx, table_id, widget_state, imgui)
        elif filt.type == "combo":
            _render_filter_combo(filt, f_idx, table_id, widget_state, imgui)

    # Detect filter changes
    curr_snap = _get_filter_snapshot(filters, table_id, widget_state)
    # Treat initial snapshot (prev_snap == "") as a change so pagination
    # resets and first row auto-selects when filters are first introduced.
    filters_changed = curr_snap != prev_snap
    widget_state.set(snap_key, curr_snap)

    visible = _filter_indexed_rows(filters, indexed, table_id, widget_state)
    total = len(rows)
    shown = len(visible)
    if shown < total:
        imgui.text_disabled(f"Showing {shown} of {total}")
    else:
        imgui.text_disabled(f"{total} rows")

    return visible, filters_changed


def _filter_indexed_rows(
    filters: list[Any],
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
    filt: Any,
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


_ROWS_PER_PAGE = 10


def _render_table_pagination(
    total_rows: int,
    table_id: str,
    widget_state: WidgetState,
    page_key: str,
    imgui: Any,
) -> tuple[int, int, bool]:
    """Render pagination controls and return (start, end, page_changed)."""
    if total_rows <= _ROWS_PER_PAGE:
        return 0, total_rows, False

    page: int = widget_state.ensure(page_key, 0)
    total_pages = (total_rows + _ROWS_PER_PAGE - 1) // _ROWS_PER_PAGE
    clamped = max(0, min(page, total_pages - 1))
    # Persist clamped value (e.g. after rows shrink from update/filter)
    if clamped != page:
        widget_state.set(page_key, clamped)
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
        widget_state.set(page_key, page)

    start = page * _ROWS_PER_PAGE
    end = min(start + _ROWS_PER_PAGE, total_rows)
    return start, end, page_changed


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


def _render_table_rows(
    indexed_rows: list[IndexedRow],
    num_cols: int,
    *,
    selectable: bool,
    table_id: str,
    widget_state: WidgetState,
    sel_key: str,
    imgui: Any,
) -> tuple[int, bool]:
    """Render table body rows, with optional row selection for detail views.

    Returns ``(selected_orig, row_clicked)`` — the currently selected
    original row index (-1 if none) and whether a row was clicked this
    frame (used by ``_maybe_copy_id`` for re-click detection).
    """
    selected_orig: int = widget_state.ensure(sel_key, -1)
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
                    widget_state.set(sel_key, orig_idx)
                    selected_orig = orig_idx
                    row_clicked = True
            else:
                imgui.text_wrapped(str(cell))
    return selected_orig, row_clicked


def _handle_table_keyboard_nav(
    indexed_rows: list[IndexedRow],
    selected_orig: int,
    sel_key: str,
    widget_state: WidgetState,
    imgui: Any,
) -> int:
    """Handle up/down arrow keyboard navigation for selectable table rows."""
    if not indexed_rows or selected_orig < 0:
        return selected_orig

    # Build ordered list of original indices in display order
    orig_indices = [orig_idx for orig_idx, _ in indexed_rows]
    if selected_orig not in orig_indices:
        return selected_orig

    cur_pos = orig_indices.index(selected_orig)

    if imgui.is_key_pressed(imgui.Key.up_arrow) and cur_pos > 0:
        new_orig = orig_indices[cur_pos - 1]
        widget_state.set(sel_key, new_orig)
        return new_orig

    if imgui.is_key_pressed(imgui.Key.down_arrow) and cur_pos < len(orig_indices) - 1:
        new_orig = orig_indices[cur_pos + 1]
        widget_state.set(sel_key, new_orig)
        return new_orig

    return selected_orig


def _render_table_detail(
    detail: Any,
    row_idx: int,
    table_id: str,
    imgui: Any,
    *,
    table_row: list[Any] | None = None,
) -> None:
    """Render the detail panel for a selected table row.

    Draws a separator, then a scrollable child region containing:
    - Heading derived from the table row (ID: Title) or detail row fallback
    - 2-column metadata grid (Field | Value | Field | Value)
    - Separator
    - Body text (wrapped, scrollable)
    """
    fields: list[str] = detail.fields
    detail_rows: list[list[Any]] = detail.rows
    body_list: list[str] = detail.body

    if row_idx >= min(len(detail_rows), len(body_list)):
        return

    row_data = detail_rows[row_idx]
    body = body_list[row_idx]

    imgui.separator()

    # Scrollable child region — takes all remaining height
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


# ---------------------------------------------------------------------------
# Render function per-element state
# ---------------------------------------------------------------------------


@dataclass
class _RenderFnState:
    """Lifecycle state for a single render_function element."""

    source: str = ""
    dialog: Any = None  # ConsentDialog | None
    executor: Any = None  # CodeExecutor | None
    denied: bool = False


@dataclass
class _Frame:
    """A named inner window in the workspace.

    Each frame is rendered as an ``imgui.begin()/end()`` window.  It owns
    one or more scenes contributed by one or more clients.  When ``layout``
    is ``"tab"`` (default), multiple scenes appear as tabs; when ``"stack"``,
    they stack vertically with collapsing headers.
    """

    frame_id: str
    title: str
    owner_fds: set[int]
    scenes: dict[str, SceneMessage]
    scene_order: list[str]
    active_tab: str | None = None
    minimized: bool = False
    cascade_index: int = 0
    initial_size: tuple[int, int] | None = None
    flags: dict[str, bool] | None = None
    layout: Literal["tab", "stack"] = "tab"


# ---------------------------------------------------------------------------
# Display server
# ---------------------------------------------------------------------------


class DisplayServer:
    """ImGui display server with non-blocking Unix socket IPC."""

    def __init__(
        self,
        socket_path: str | None = None,
        *,
        test_auto_click: bool = False,
    ) -> None:
        self._socket_path = Path(socket_path or str(default_socket_path()))
        self._server_sock: socket.socket | None = None
        self._clients: list[socket.socket] = []
        self._readers: dict[int, FrameReader] = {}  # fd -> reader
        self._fd_to_client: dict[int, socket.socket] = {}  # fd -> socket (O(1) lookup)
        self._client_names: dict[int, str] = {}  # fd -> display name
        self._scenes: dict[str, SceneMessage] = {}  # ordered by insertion
        self._scene_order: list[str] = []  # explicit tab order
        self._active_tab: str | None = None  # currently selected tab
        self._frames: dict[str, _Frame] = {}  # frame_id → frame
        self._focus_frame_id: str | None = None  # auto-focus on next render
        self._scene_to_frame: dict[str, str] = {}  # scene_id → frame_id
        self._scene_to_owner: dict[str, int] = {}  # scene_id → contributing fd
        self._scene_widget_state: dict[str, WidgetState] = {}  # per-scene
        self._scene_render_fn_state: dict[str, dict[str, _RenderFnState]] = {}
        self._event_queue: list[InteractionMessage] = []
        self._textures = TextureCache()
        self._widget_state = WidgetState()  # active scene's state (swapped)
        self._dirty_windows: set[str] = set()
        self._agent_menus: list[dict[str, Any]] = []
        self._menu_registrations: dict[int, list[dict[str, Any]]] = {}  # fd → items
        self._menu_owners: dict[str, int] = {}  # item_id → fd
        self._render_fn_state: dict[str, _RenderFnState] = {}  # active (swapped)
        self._themes: list[Any] = []
        self._decorated: bool = True
        self._opacity: float = 1.0
        self._font_scale: float = 1.1
        self._fit_all_frames: bool = False
        self._world_menu_open: bool = False
        self._world_menu_pinned: bool = False
        self._world_menu_spawn_pos: tuple[float, float] | None = None
        self._test_auto_click = test_auto_click

    @property
    def socket_path(self) -> Path:
        return self._socket_path

    # -- font loading ------------------------------------------------------

    @staticmethod
    def _find_fonts() -> tuple[str | None, list[str]]:
        """Find system fonts for broad Unicode coverage.

        Returns ``(primary, merge_fonts)`` where *primary* is a text font
        with good coverage and *merge_fonts* are symbol fonts merged on
        top to fill gaps (e.g. mathematical angle brackets, Z notation).
        """

        def _first_existing(*candidates: str) -> str | None:
            for p in candidates:
                if Path(p).is_file():
                    return p
            return None

        merge: list[str] = []

        if platform.system() == "Darwin":
            primary = _first_existing(
                "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
                "/System/Library/Fonts/Helvetica.ttc",
            )
            # Apple Symbols fills gaps (math angle brackets U+27E8/E9, etc.)
            sym = _first_existing("/System/Library/Fonts/Apple Symbols.ttf")
            if sym:
                merge.append(sym)
            # STIX Two Math covers Mathematical Alphanumeric Symbols
            # (U+1D400-1D7FF) -- needed for Z notation double-struck letters
            math = _first_existing(
                "/System/Library/Fonts/Supplemental/STIXTwoMath.otf",
                "/Library/Fonts/STIXTwoMath.otf",
            )
            if math:
                merge.append(math)
        else:
            # Linux — DejaVu has good symbol coverage; Noto as fallback
            primary = _first_existing(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/TTF/DejaVuSans.ttf",
                "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf",
                "/usr/share/fonts/noto/NotoSans-Regular.ttf",
            )
            # Noto Sans Symbols for anything DejaVu misses
            sym = _first_existing(
                "/usr/share/fonts/truetype/noto/NotoSansSymbols2-Regular.ttf",
                "/usr/share/fonts/noto/NotoSansSymbols2-Regular.ttf",
            )
            if sym:
                merge.append(sym)
            # Noto Sans Math covers Mathematical Alphanumeric Symbols
            # (U+1D400-1D7FF) -- needed for Z notation double-struck letters
            math = _first_existing(
                "/usr/share/fonts/truetype/noto/NotoSansMath-Regular.ttf",
                "/usr/share/fonts/noto/NotoSansMath-Regular.ttf",
            )
            if math:
                merge.append(math)

        return primary, merge

    def _load_fonts(self) -> None:
        """hello_imgui ``load_additional_fonts`` callback.

        Loads a system font with Unicode symbol coverage as the default
        font, replacing ImGui's built-in ProggyClean (Latin-only).
        A second symbol font is merged on top to fill remaining gaps
        (Z notation angle brackets, additional mathematical symbols).
        """
        from imgui_bundle import hello_imgui

        primary, merge_fonts = self._find_fonts()
        if primary is None:
            logger.error(
                "No Unicode font found — using ImGui default (Latin-only). "
                "Unicode symbols will not render correctly."
            )
            return

        params = hello_imgui.FontLoadingParams()
        params.inside_assets = False
        hello_imgui.load_font(primary, 16.0, params)
        logger.info("Loaded primary font: %s", primary)

        for sym_path in merge_fonts:
            merge_params = hello_imgui.FontLoadingParams()
            merge_params.inside_assets = False
            merge_params.merge_to_last_font = True
            hello_imgui.load_font(sym_path, 16.0, merge_params)
            logger.info("Merged symbol font: %s", sym_path)

    # -- public entry point ------------------------------------------------

    def run(self) -> None:
        """Start the display server (blocking — ImGui owns the main loop)."""
        # Set process name (visible in ps, top, Activity Monitor)
        try:
            import setproctitle  # pyright: ignore[reportMissingImports]

            setproctitle.setproctitle("Lux")
        except ImportError:
            pass

        from imgui_bundle import hello_imgui, immapp

        runner_params = hello_imgui.RunnerParams()
        runner_params.app_window_params.window_title = "Lux"
        runner_params.app_window_params.window_geometry.size = (1200, 800)
        runner_params.imgui_window_params.show_menu_bar = True
        runner_params.imgui_window_params.show_menu_app = False
        runner_params.imgui_window_params.show_menu_view = False
        runner_params.imgui_window_params.show_menu_view_themes = False
        runner_params.imgui_window_params.show_status_bar = False
        runner_params.imgui_window_params.show_status_fps = False
        runner_params.imgui_window_params.remember_status_bar_settings = False
        runner_params.callbacks.load_additional_fonts = self._load_fonts
        runner_params.callbacks.show_menus = self._show_menus
        runner_params.callbacks.post_init = self._on_post_init
        runner_params.callbacks.show_gui = self._on_frame
        runner_params.callbacks.before_exit = self._on_exit
        runner_params.fps_idling.fps_idle = 30.0

        addons = immapp.AddOnsParams()
        addons.with_implot = True
        # Set markdown regular_size to match the system font visually.
        # imgui_md loads Roboto (bundled) which renders larger than system
        # fonts at the same nominal px.  Do NOT also set with_markdown=True
        # — InitializeMarkdown has a static guard that silently drops the
        # second call, so the custom options would be ignored.
        try:
            from imgui_bundle import imgui_md

            md_opts = imgui_md.MarkdownOptions()
            md_opts.font_options.regular_size = 13.0
            addons.with_markdown_options = md_opts
        except ImportError:
            addons.with_markdown = True

        immapp.run(runner_params, addons)

    # -- ImGui callbacks ---------------------------------------------------

    def _on_post_init(self) -> None:
        """Called once the OpenGL context is ready."""
        from imgui_bundle import hello_imgui, imgui

        # Ensure docking is enabled (drag-merge frames into tabs).
        io = imgui.get_io()
        io.config_flags |= imgui.ConfigFlags_.docking_enable.value

        self._themes = list(hello_imgui.ImGuiTheme_)
        self._setup_socket()
        write_pid_file(self._socket_path)

        # macOS: hide from Dock after GLFW init (which overrides earlier calls)
        if platform.system() == "Darwin":
            try:
                import AppKit as _AppKit  # pyright: ignore[reportMissingImports,reportAttributeAccessIssue]

                _ak: Any = _AppKit
                _ak.NSApplication.sharedApplication().setActivationPolicy_(
                    _ak.NSApplicationActivationPolicyAccessory
                )
            except Exception:  # noqa: BLE001
                logger.debug("Could not hide Dock icon", exc_info=True)

        logger.info("Display server listening on %s", self._socket_path)

    def _on_frame(self) -> None:
        """Called every frame by ImGui."""
        self._accept_connections()
        self._poll_clients()
        self._render_scene()
        self._flush_events()

    def _on_exit(self) -> None:
        """Called before the window closes."""
        self._textures.cleanup()
        for client in self._clients:
            client.close()
        self._clients.clear()
        self._readers.clear()
        self._fd_to_client.clear()
        self._menu_registrations.clear()
        self._menu_owners.clear()
        if self._server_sock is not None:
            self._server_sock.close()
            self._server_sock = None
        self._socket_path.unlink(missing_ok=True)
        remove_pid_file(self._socket_path)
        logger.info("Display server stopped")

    # -- menu bar ----------------------------------------------------------

    def _show_menus(self) -> None:
        from imgui_bundle import imgui

        try:
            self._show_lux_menu(imgui)
            self._show_apps_menu(imgui)
            self._show_debug_menu(imgui)
            self._show_window_menu(imgui)
            self._show_help_menu(imgui)
            for menu in self._agent_menus:
                self._show_agent_menu(imgui, menu)
        except Exception:
            logger.exception("Error rendering menus")

    def _apply_theme(self, theme_name: str) -> None:
        """Apply a theme by snake_case name (e.g. 'imgui_colors_light')."""
        from imgui_bundle import hello_imgui

        for theme in self._themes:
            if theme.name == theme_name:
                hello_imgui.apply_theme(theme)
                return
        logger.warning("Unknown theme %r", theme_name)

    def _show_window_menu(self, imgui: Any) -> None:
        from imgui_bundle import hello_imgui

        if not imgui.begin_menu("Windows"):
            return
        try:
            self._show_window_frame_items(imgui)
            imgui.separator()
            self._show_window_chrome_items(imgui, hello_imgui)
        finally:
            imgui.end_menu()

    def _show_window_frame_items(self, imgui: Any) -> bool:
        """Render frame management items. Returns True if any item clicked."""
        clicked = False
        has_frames = bool(self._frames)
        has_visible = has_frames and any(not f.minimized for f in self._frames.values())
        has_minimized = has_frames and any(f.minimized for f in self._frames.values())

        if imgui.menu_item("Collapse All", "", False, has_visible)[0]:  # noqa: FBT003
            for f in self._frames.values():
                f.minimized = True
            clicked = True
        if imgui.menu_item("Expand All", "", False, has_minimized)[0]:  # noqa: FBT003
            for f in self._frames.values():
                f.minimized = False
            clicked = True
        if imgui.menu_item("Fit All", "", False, has_frames)[0]:  # noqa: FBT003
            self._fit_all_frames = True
            clicked = True
        return clicked

    def _show_window_chrome_items(self, imgui: Any, hello_imgui: Any) -> bool:
        """Render window chrome items. Returns True if any item clicked."""
        clicked = False
        if imgui.menu_item("Clear All", "", False)[0]:  # noqa: FBT003
            self._scenes.clear()
            self._scene_order.clear()
            self._active_tab = None
            self._scene_widget_state.clear()
            self._scene_render_fn_state.clear()
            self._event_queue.clear()
            self._dirty_windows.clear()
            self._widget_state = WidgetState()
            self._render_fn_state = {}
            for fid in list(self._frames):
                self._close_frame(fid)
            clicked = True
        if imgui.menu_item("Reset Size", "", False)[0]:  # noqa: FBT003
            hello_imgui.change_window_size((1200, 800))
            clicked = True
        return clicked

    def _show_debug_menu(self, imgui: Any) -> None:
        if not imgui.begin_menu("Debug"):
            return
        try:
            self._show_debug_items(imgui)
        finally:
            imgui.end_menu()

    def _show_debug_items(self, imgui: Any) -> bool:
        """Render debug items. Returns True if any item clicked."""
        clicked: bool = imgui.menu_item("Dump Scene JSON", "", False)[0]  # noqa: FBT003
        if clicked:
            import json

            state: dict[str, Any] = {
                "frames": {
                    fid: {
                        "title": f.title,
                        "minimized": f.minimized,
                        "scene_count": len(f.scenes),
                        "scenes": list(f.scene_order),
                    }
                    for fid, f in self._frames.items()
                },
                "scenes": {
                    sid: {
                        "title": s.title,
                        "element_count": len(s.elements),
                    }
                    for sid, s in self._scenes.items()
                },
                "clients": dict(self._client_names),
                "menu_registrations": {
                    str(fd): len(items)
                    for fd, items in self._menu_registrations.items()
                },
            }
            print(json.dumps(state, indent=2))  # noqa: T201 — user-initiated debug dump
        return clicked

    def _show_help_menu(self, imgui: Any) -> None:
        if not imgui.begin_menu("Help"):
            return
        try:
            self._show_help_items(imgui)
        finally:
            imgui.end_menu()

    def _show_help_items(self, imgui: Any) -> bool:
        """Render help items. Returns True if any item clicked."""
        from punt_lux import __version__

        imgui.menu_item(
            f"Lux v{__version__}",
            "",
            False,  # noqa: FBT003
            False,  # noqa: FBT003
        )
        return False  # version label is not clickable

    def _check_world_menu_background_click(self, imgui: Any) -> None:
        """Toggle World panel on left-click on the main window background.

        Uses ``is_window_hovered()`` (no flags) which checks whether the
        *current* window (the main/root window at this point in the render
        loop) is hovered.  When a frame or the World panel is on top,
        the main window is not considered hovered, so clicks on frames
        are ignored.

        The dock bar renders later in the frame (its ``invisible_button``
        items and ``##dock_bar`` window haven't been emitted yet), so the
        hover checks above can't exclude it.  An explicit dock bar rect
        check handles this case.
        """
        if not imgui.is_mouse_clicked(imgui.MouseButton_.left):
            return
        if imgui.is_any_item_hovered():
            return
        # Current window = main window.  False when a frame covers the spot.
        if not imgui.is_window_hovered():
            return
        # Dock bar renders later in the frame, so its items/window aren't
        # yet in ImGui's hover state.  Reject clicks in its region.
        if any(f.minimized for f in self._frames.values()):
            viewport = imgui.get_main_viewport()
            mouse = imgui.get_mouse_pos()
            bar_top = viewport.pos.y + viewport.size.y - self._DOCK_BAR_HEIGHT
            if mouse.y >= bar_top:
                return
        self._world_menu_open = not self._world_menu_open
        if self._world_menu_open:
            pos = imgui.get_mouse_pos()
            self._world_menu_spawn_pos = (pos.x, pos.y)

    def _render_world_panel(self, imgui: Any) -> None:
        """Render the detached World menu as a floating window."""
        if not self._world_menu_open:
            return

        flags = (
            imgui.WindowFlags_.no_collapse.value
            | imgui.WindowFlags_.always_auto_resize.value
        )
        imgui.set_next_window_size((220, 0), imgui.Cond_.first_use_ever.value)
        if self._world_menu_spawn_pos is not None:
            imgui.set_next_window_pos(
                self._world_menu_spawn_pos, imgui.Cond_.always.value
            )
            self._world_menu_spawn_pos = None

        still_open = True
        _, still_open = imgui.begin("World###world_panel", still_open, flags)
        if not still_open:
            self._world_menu_open = False
            self._world_menu_pinned = False
            imgui.end()
            return

        # Pin dot — filled ● when pinned, hollow ○ when unpinned.
        pin_dot = "\u25cf" if self._world_menu_pinned else "\u25cb"
        if imgui.small_button(f"{pin_dot}##pin"):
            self._world_menu_pinned = not self._world_menu_pinned
        imgui.separator()

        clicked_any = self._render_world_panel_sections(imgui)

        imgui.end()

        # Auto-close on click when unpinned.
        if clicked_any and not self._world_menu_pinned:
            self._world_menu_open = False

    def _render_world_panel_sections(self, imgui: Any) -> bool:
        """Render all World panel sections. Returns True if any item clicked."""
        from imgui_bundle import hello_imgui

        clicked_any = False

        if imgui.begin_menu("Lux##world"):
            try:
                clicked_any = self._show_lux_items(imgui) or clicked_any
            finally:
                imgui.end_menu()

        # Applications submenu: agent-registered menu items grouped by client.
        if self._menu_registrations:
            clicked_any = self._render_world_panel_apps(imgui) or clicked_any

        if imgui.begin_menu("Debug##world"):
            try:
                clicked_any = self._show_debug_items(imgui) or clicked_any
            finally:
                imgui.end_menu()
        if imgui.begin_menu("Windows##world"):
            try:
                clicked_any = self._show_window_frame_items(imgui) or clicked_any
                imgui.separator()
                chrome_clicked = self._show_window_chrome_items(imgui, hello_imgui)
                clicked_any = chrome_clicked or clicked_any
            finally:
                imgui.end_menu()
        if imgui.begin_menu("Help##world"):
            try:
                clicked_any = self._show_help_items(imgui) or clicked_any
            finally:
                imgui.end_menu()
        return clicked_any

    @staticmethod
    def _display_name(raw: str) -> str:
        """Derive a display name from a client name.

        Strips common suffixes like "-mcp" and title-cases the result.
        ``"lux-mcp"`` → ``"Lux"``, ``"vox-mcp"`` → ``"Vox"``.
        """
        name = raw.removesuffix("-mcp")
        return name.replace("-", " ").title()

    def _render_world_panel_apps(self, imgui: Any) -> bool:
        """Render Applications submenu in the World panel."""
        if not imgui.begin_menu("Applications##world"):
            return False
        clicked = False
        try:
            for name, fd, items in self._sorted_app_clients():
                if imgui.begin_menu(f"{name}##{fd}"):
                    try:
                        items_sorted = sorted(items, key=lambda i: i.get("label") or "")
                        for item in items_sorted:
                            rendered = self._render_registered_item(
                                imgui, item, "Applications"
                            )
                            clicked = clicked or rendered
                    finally:
                        imgui.end_menu()
        finally:
            imgui.end_menu()
        return clicked

    @staticmethod
    def _set_glfw_decorated(*, decorated: bool) -> None:
        """Toggle window decoration at runtime via GLFW.

        Uses RTLD_NOLOAD to grab the already-loaded libglfw handle
        rather than loading a second copy (which triggers duplicate
        Objective-C class warnings on macOS).
        """
        import ctypes

        from imgui_bundle import hello_imgui

        glfw_decorated = 0x00020005  # GLFW_DECORATED
        window_addr = hello_imgui.get_glfw_window_address()  # type: ignore[attr-defined]

        # RTLD_NOLOAD (0x10 on macOS) returns the existing handle
        # without loading a second copy of the library.
        rtld_noload = 0x10
        glfw_lib = ctypes.CDLL("libglfw.3.dylib", mode=rtld_noload)
        glfw_lib.glfwSetWindowAttrib.argtypes = [
            ctypes.c_void_p,
            ctypes.c_int,
            ctypes.c_int,
        ]
        glfw_lib.glfwSetWindowAttrib(
            ctypes.c_void_p(window_addr),
            glfw_decorated,
            int(decorated),
        )

    @staticmethod
    def _set_glfw_opacity(*, opacity: float) -> None:
        """Set window opacity at runtime via GLFW."""
        import ctypes

        from imgui_bundle import hello_imgui

        window_addr = hello_imgui.get_glfw_window_address()  # type: ignore[attr-defined]
        rtld_noload = 0x10
        glfw_lib = ctypes.CDLL("libglfw.3.dylib", mode=rtld_noload)
        glfw_lib.glfwSetWindowOpacity.argtypes = [ctypes.c_void_p, ctypes.c_float]
        glfw_lib.glfwSetWindowOpacity(ctypes.c_void_p(window_addr), opacity)

    def _show_lux_menu(self, imgui: Any) -> None:
        if not imgui.begin_menu("Lux"):
            return
        try:
            self._show_lux_items(imgui)
        finally:
            imgui.end_menu()

    def _show_apps_menu(self, imgui: Any) -> None:
        """Render the Applications menu in the menu bar."""
        if not self._menu_registrations:
            return
        if not imgui.begin_menu("Applications"):
            return
        try:
            for name, fd, items in self._sorted_app_clients():
                if imgui.begin_menu(f"{name}##{fd}"):
                    try:
                        items_sorted = sorted(items, key=lambda i: i.get("label") or "")
                        for item in items_sorted:
                            self._render_registered_item(imgui, item, "Applications")
                    finally:
                        imgui.end_menu()
        finally:
            imgui.end_menu()

    def _sorted_app_clients(
        self,
    ) -> list[tuple[str, int, list[dict[str, Any]]]]:
        """Return registered clients sorted by display name."""
        clients: list[tuple[str, int, list[dict[str, Any]]]] = []
        for fd, items in self._menu_registrations.items():
            if items:
                raw = self._client_names.get(fd, f"Client {fd}")
                clients.append((self._display_name(raw), fd, items))
        clients.sort(key=lambda c: c[0].lower())
        return clients

    def _render_registered_item(
        self,
        imgui: Any,
        item: dict[str, Any],
        menu_name: str,
    ) -> bool:
        """Render a single registered menu item. Returns True if clicked."""
        label = item.get("label")
        if not isinstance(label, str):
            return False
        if label == "---":
            imgui.separator()
            return False
        enabled = item.get("enabled", True)
        clicked, _ = imgui.menu_item(
            label,
            item.get("shortcut", ""),
            False,  # noqa: FBT003
            enabled,
        )
        if clicked and isinstance(item.get("id"), str):
            self._event_queue.append(
                InteractionMessage(
                    element_id=item["id"],
                    action="menu",
                    ts=time.time(),
                    value={
                        "menu": menu_name,
                        "item": label,
                    },
                )
            )
        return bool(clicked)

    def _show_lux_items(self, imgui: Any) -> bool:
        """Render Lux menu items. Returns True if any item clicked."""
        from imgui_bundle import hello_imgui

        clicked = False

        # Settings submenu: theme, chrome, opacity.
        if imgui.begin_menu("Settings"):
            try:
                clicked = self._show_settings_items(imgui) or clicked
            finally:
                imgui.end_menu()

        imgui.separator()

        if imgui.menu_item("Increase Font", "", False)[0]:  # noqa: FBT003
            self._font_scale = min(round(self._font_scale + 0.1, 1), 3.0)
            clicked = True
        if imgui.menu_item("Decrease Font", "", False)[0]:  # noqa: FBT003
            self._font_scale = max(round(self._font_scale - 0.1, 1), 0.5)
            clicked = True

        imgui.separator()

        if imgui.menu_item("Quit", "Cmd+Q", False)[0]:  # noqa: FBT003
            hello_imgui.get_runner_params().app_shall_exit = True
            clicked = True
        return clicked

    def _show_settings_items(self, imgui: Any) -> bool:
        """Render Settings submenu contents. Returns True if any item clicked."""
        from imgui_bundle import hello_imgui

        clicked = False

        # Theme picker.
        if imgui.begin_menu("Theme"):
            try:
                for theme in self._themes:
                    name = theme.name.replace("_", " ").title()
                    if imgui.menu_item(name, "", False)[0]:  # noqa: FBT003
                        hello_imgui.apply_theme(theme)
                        clicked = True
            finally:
                imgui.end_menu()

        imgui.separator()

        # Window chrome toggles.
        params = hello_imgui.get_runner_params()
        wp = params.app_window_params
        top_toggled, wp.top_most = imgui.menu_item("Always on Top", "", wp.top_most)
        if top_toggled:
            clicked = True

        toggled, _ = imgui.menu_item("Borderless", "", not self._decorated)
        if toggled:
            self._decorated = not self._decorated
            self._set_glfw_decorated(decorated=self._decorated)
            clicked = True

        imgui.separator()

        # Opacity presets.
        if imgui.begin_menu("Opacity"):
            try:
                for pct in (25, 50, 75, 100):
                    val = pct / 100.0
                    current = abs(self._opacity - val) < 0.05
                    if imgui.menu_item(f"{pct}%", "", current)[0]:
                        self._opacity = val
                        self._set_glfw_opacity(opacity=val)
                        clicked = True
            finally:
                imgui.end_menu()
        return clicked

    def _show_agent_menu(self, imgui: Any, menu: dict[str, Any]) -> None:
        if imgui.begin_menu(menu.get("label", "Custom")):
            try:
                for item in menu.get("items", []):
                    label = item.get("label")
                    if not isinstance(label, str):
                        continue
                    if label == "---":
                        imgui.separator()
                        continue
                    enabled = item.get("enabled", True)
                    clicked, _ = imgui.menu_item(
                        label,
                        item.get("shortcut", ""),
                        False,  # noqa: FBT003
                        enabled,
                    )
                    if clicked and isinstance(item.get("id"), str):
                        self._event_queue.append(
                            InteractionMessage(
                                element_id=item["id"],
                                action="menu",
                                ts=time.time(),
                                value={
                                    "menu": menu.get("label", "Custom"),
                                    "item": label,
                                },
                            )
                        )
            finally:
                imgui.end_menu()

    # -- socket lifecycle --------------------------------------------------

    def _setup_socket(self) -> None:
        cleanup_stale_socket(self._socket_path)
        self._socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._socket_path.parent.chmod(0o700)
        if self._socket_path.exists():
            if self._socket_path.is_socket():
                self._socket_path.unlink()
            else:
                msg = f"Path exists and is not a socket: {self._socket_path}"
                raise RuntimeError(msg)
        self._server_sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server_sock.bind(str(self._socket_path))
        self._server_sock.listen(5)
        self._server_sock.setblocking(False)  # noqa: FBT003

    def _accept_connections(self) -> None:
        if self._server_sock is None:
            return
        readable, _, _ = select.select([self._server_sock], [], [], 0)
        if readable:
            try:
                conn, _ = self._server_sock.accept()
            except (BlockingIOError, OSError):
                return
            conn.setblocking(False)  # noqa: FBT003
            fd = conn.fileno()
            self._clients.append(conn)
            self._readers[fd] = FrameReader()
            self._fd_to_client[fd] = conn
            logger.debug("Client connected (total: %d)", len(self._clients))
            self._send_to_client(conn, ReadyMessage())

    def _poll_clients(self) -> None:
        if not self._clients:
            return
        readable, _, errored = select.select(self._clients, [], self._clients, 0)
        for sock in errored:
            self._remove_client(sock)
        for sock in readable:
            if sock in self._clients:
                self._read_from_client(sock)

    def _read_from_client(self, sock: socket.socket) -> None:
        reader = self._readers.get(sock.fileno())
        if reader is None:
            return
        try:
            data = sock.recv(65536)
            if not data:
                self._remove_client(sock)
                return
            reader.feed(data)
            if reader.buffer_size > MAX_MESSAGE_SIZE + HEADER_SIZE:
                logger.warning("Buffer overflow from fd %d", sock.fileno())
                self._remove_client(sock)
                return
            # Deserialize all complete frames — KeyError/TypeError/ValueError
            # here means malformed wire data, not a handler bug.
            try:
                messages = reader.drain_typed()
            except (ValueError, KeyError, TypeError):
                fd = sock.fileno()
                logger.warning("Malformed message from fd %d", fd)
                self._remove_client(sock)
                return
            for msg in messages:
                logger.debug(
                    "Received %s from fd=%s", type(msg).__name__, sock.fileno()
                )
                self._handle_message(sock, msg)
                if sock not in self._clients:
                    return  # removed during handle (e.g. send failed)
        except (ConnectionError, OSError):
            self._remove_client(sock)

    def _remove_client(self, sock: socket.socket) -> None:
        if sock not in self._clients:
            return  # already removed — make idempotent
        self._clients.remove(sock)
        try:
            fd = sock.fileno()
        except OSError:
            fd = None
            logger.warning("Client socket fd unavailable — skipping cleanup")
        if fd is not None:
            self._readers.pop(fd, None)
            self._fd_to_client.pop(fd, None)
            self._client_names.pop(fd, None)
            self._menu_registrations.pop(fd, None)
            self._menu_owners = {k: v for k, v in self._menu_owners.items() if v != fd}
            # Remove this client's scenes from shared frames.
            # _dismiss_framed_scene may auto-close empty frames (mutating
            # _frames), so iterate over a snapshot.
            for f in list(self._frames.values()):
                f.owner_fds.discard(fd)
                owned_scenes = [
                    sid for sid in f.scene_order if self._scene_to_owner.get(sid) == fd
                ]
                for sid in owned_scenes:
                    if f.frame_id in self._frames:
                        self._dismiss_framed_scene(f, sid, notify=False)
        with contextlib.suppress(OSError):
            sock.close()
        logger.debug("Client disconnected (remaining: %d)", len(self._clients))

    def _send_to_client(self, sock: socket.socket, msg: Message) -> None:
        try:
            sock.sendall(encode_message(msg))
        except (ConnectionError, OSError):
            self._remove_client(sock)

    # -- message handling --------------------------------------------------

    def _handle_message(self, sock: socket.socket, msg: Message) -> None:
        if isinstance(msg, SceneMessage):
            self._handle_scene(sock, msg)
        elif isinstance(msg, UpdateMessage):
            self._apply_update(msg)
            self._send_to_client(
                sock,
                AckMessage(scene_id=msg.scene_id, ts=time.time()),
            )
        elif isinstance(msg, ClearMessage):
            self._scenes.clear()
            self._scene_order.clear()
            self._active_tab = None
            self._frames.clear()
            self._scene_to_frame.clear()
            self._scene_to_owner.clear()
            self._scene_widget_state.clear()
            self._scene_render_fn_state.clear()
            self._event_queue.clear()
            self._dirty_windows.clear()
            self._widget_state = WidgetState()
            self._render_fn_state = {}
        elif isinstance(msg, RegisterMenuMessage):
            self._handle_register_menu(sock, msg)
        elif isinstance(msg, MenuMessage):
            self._agent_menus = msg.menus
        elif isinstance(msg, ThemeMessage):
            self._apply_theme(msg.theme)
        elif isinstance(msg, ConnectMessage):
            self._handle_connect(sock, msg)
        elif isinstance(msg, PingMessage):
            self._send_to_client(sock, PongMessage(ts=msg.ts, display_ts=time.time()))
        elif isinstance(msg, UnknownMessage):
            logger.debug("Ignoring unknown message type %r", msg.raw_type)

    def _sanitize_menu_items(
        self, fd: int, items: list[Any]
    ) -> list[dict[str, Any]] | None:
        """Validate and deduplicate menu items for registration.

        Returns sanitized items, or None if registration should be rejected
        (item ID owned by a different client).
        """
        seen_ids: set[str] = set()
        sanitized: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            item_id = item.get("id")
            if item_id is not None and not isinstance(item_id, str):
                continue
            if item_id is not None:
                if item_id in seen_ids:
                    continue
                owner_fd = self._menu_owners.get(item_id)
                if owner_fd is not None and owner_fd != fd:
                    logger.warning(
                        "Menu item %r already owned by fd %d, "
                        "rejecting registration from fd %d",
                        item_id,
                        owner_fd,
                        fd,
                    )
                    return None
                seen_ids.add(item_id)
            sanitized.append(item)
        return sanitized

    def _handle_connect(self, sock: socket.socket, msg: ConnectMessage) -> None:
        """Record a client's display name (idempotent)."""
        name = msg.name.strip()
        if not name:
            logger.warning("ConnectMessage with empty name — ignored")
            return
        try:
            fd = sock.fileno()
        except OSError:
            return
        self._client_names[fd] = name
        logger.info("Client fd=%d identified as %r", fd, name)

    def client_name(self, fd: int) -> str | None:
        """Return the display name for a connected client, or ``None``."""
        return self._client_names.get(fd)

    def _handle_register_menu(
        self, sock: socket.socket, msg: RegisterMenuMessage
    ) -> None:
        """Register menu items owned by this client into the Applications menu."""
        logger.info(
            "RegisterMenuMessage from fd=%s: %d items",
            sock.fileno(),
            len(msg.items),
        )
        try:
            fd = sock.fileno()
        except OSError:
            return
        sanitized = self._sanitize_menu_items(fd, msg.items)
        if sanitized is None:
            return  # rejected — ID collision
        # Remove old ownership entries for this fd
        self._menu_owners = {k: v for k, v in self._menu_owners.items() if v != fd}
        # Store new items (empty list clears this client's items)
        if sanitized:
            self._menu_registrations[fd] = sanitized
        else:
            self._menu_registrations.pop(fd, None)
        # Update ownership
        for item in sanitized:
            item_id = item.get("id")
            if item_id is not None:
                self._menu_owners[item_id] = fd

    def _handle_scene(self, sock: socket.socket, msg: SceneMessage) -> None:
        if msg.frame_id is not None:
            self._handle_framed_scene(sock, msg)
            return
        is_new = msg.id not in self._scenes
        old_scene = self._scenes.get(msg.id)
        self._scenes[msg.id] = msg
        if is_new:
            self._scene_order.append(msg.id)
            self._scene_widget_state[msg.id] = WidgetState()
            self._scene_render_fn_state[msg.id] = {}
            self._active_tab = msg.id
            for elem in msg.elements:
                if isinstance(elem, WindowElement):
                    self._dirty_windows.add(elem.id)
        else:
            self._replace_scene_state(msg, old_scene)
        self._send_to_client(sock, AckMessage(scene_id=msg.id, ts=time.time()))
        if self._test_auto_click:
            self._auto_click_buttons(msg)

    def _replace_scene_state(
        self,
        msg: SceneMessage,
        old_scene: SceneMessage | None = None,
    ) -> None:
        """Drain stale events and reset widget state for a replaced scene."""
        if old_scene is not None:
            old_ids: set[str] = set()
            for elem in old_scene.elements:
                old_ids.update(_collect_ids(elem))
            new_ids: set[str] = set()
            for elem in msg.elements:
                new_ids.update(_collect_ids(elem))
            stale_ids = old_ids - new_ids
            self._event_queue = [
                ev for ev in self._event_queue if ev.element_id not in stale_ids
            ]
        self._scene_widget_state[msg.id].clear()
        self._scene_render_fn_state[msg.id].clear()

    def _next_cascade_index(self) -> int:
        """Return the smallest non-negative index not used by any open frame."""
        used = {f.cascade_index for f in self._frames.values()}
        idx = 0
        while idx in used:
            idx += 1
        return idx

    def _handle_framed_scene(self, sock: socket.socket, msg: SceneMessage) -> None:
        """Route a scene into a frame, creating the frame if needed."""
        frame_id = msg.frame_id
        if frame_id is None:
            return
        try:
            fd = sock.fileno()
        except OSError:
            return
        frame = self._frames.get(frame_id)
        if frame is None:
            title = msg.frame_title or msg.title or frame_id
            frame = _Frame(
                frame_id=frame_id,
                title=title,
                owner_fds={fd},
                scenes={},
                scene_order=[],
                cascade_index=self._next_cascade_index(),
                initial_size=msg.frame_size,
                flags=msg.frame_flags,
                layout=msg.frame_layout or "tab",
            )
            self._frames[frame_id] = frame
        else:
            frame.owner_fds.add(fd)
        self._upsert_scene_in_frame(frame, msg)
        self._scene_to_owner[msg.id] = fd
        if msg.frame_title:
            frame.title = msg.frame_title
        if msg.frame_flags is not None:
            frame.flags = msg.frame_flags
        if msg.frame_layout is not None:
            frame.layout = msg.frame_layout
        frame.minimized = False
        self._focus_frame_id = frame_id
        self._send_to_client(sock, AckMessage(scene_id=msg.id, ts=time.time()))
        if self._test_auto_click:
            self._auto_click_buttons(msg)

    def _upsert_scene_in_frame(self, frame: _Frame, msg: SceneMessage) -> None:
        """Add or replace a scene within a frame."""
        # If this scene_id exists elsewhere, remove it from the old location
        # to prevent the same scene rendering in multiple places.
        old_frame_id = self._scene_to_frame.get(msg.id)
        if old_frame_id is not None and old_frame_id != frame.frame_id:
            old_frame = self._frames.get(old_frame_id)
            if old_frame is not None:
                self._dismiss_framed_scene(old_frame, msg.id)
        elif msg.id in self._scenes:
            self._dismiss_scene(msg.id)
        is_new = msg.id not in frame.scenes
        old_scene = frame.scenes.get(msg.id)
        frame.scenes[msg.id] = msg
        if is_new:
            frame.scene_order.append(msg.id)
            self._scene_widget_state[msg.id] = WidgetState()
            self._scene_render_fn_state[msg.id] = {}
            frame.active_tab = msg.id
            self._scene_to_frame[msg.id] = frame.frame_id
            for elem in msg.elements:
                if isinstance(elem, WindowElement):
                    self._dirty_windows.add(elem.id)
        else:
            self._replace_scene_state(msg, old_scene)

    def _resolve_scene(self, scene_id: str) -> SceneMessage | None:
        """Find a scene in either unframed or framed storage."""
        scene = self._scenes.get(scene_id)
        if scene is not None:
            return scene
        frame_id = self._scene_to_frame.get(scene_id)
        if frame_id is not None:
            frame = self._frames.get(frame_id)
            if frame is not None:
                return frame.scenes.get(scene_id)
        return None

    def _apply_update(self, msg: UpdateMessage) -> None:
        scene = self._resolve_scene(msg.scene_id)
        if scene is None:
            return
        ws = self._scene_widget_state.get(msg.scene_id)
        rfs = self._scene_render_fn_state.get(msg.scene_id)
        for patch in msg.patches:
            result = _find_element(scene.elements, patch.id)
            if result is None:
                continue
            parent_list, idx = result
            if patch.remove:
                removed = parent_list.pop(idx)
                for eid in _collect_ids(removed):
                    if ws is not None:
                        ws.set(eid, None)
                        ws.clear_suffix(f"_{eid}")
                    if rfs is not None:
                        rfs.pop(eid, None)
            elif patch.set:
                self._apply_patch_set(parent_list[idx], patch.set, ws)

    def _apply_patch_set(
        self,
        elem: Element,
        fields: dict[str, Any],
        ws: WidgetState | None = None,
    ) -> None:
        """Apply a set-patch to an element and sync widget/window state."""
        for k, v in fields.items():
            if k in ("id", "kind"):
                continue
            if hasattr(elem, k):
                setattr(elem, k, v)
        eid = getattr(elem, "id", None)
        target_ws = ws if ws is not None else self._widget_state
        if eid is not None and fields.keys() & {"value", "selected", "items"}:
            target_ws.set(eid, _widget_value(elem))
        if (
            eid is not None
            and isinstance(elem, WindowElement)
            and fields.keys() & {"x", "y", "width", "height"}
        ):
            self._dirty_windows.add(eid)

    def _auto_click_buttons(self, msg: SceneMessage) -> None:
        """Enqueue synthetic interactions for testable elements (test mode)."""
        for elem in msg.elements:
            if elem.kind == "button" and not getattr(elem, "disabled", False):
                eid: str = getattr(elem, "id", "")
                action: str = getattr(elem, "action", None) or eid
                self._event_queue.append(
                    InteractionMessage(
                        element_id=eid,
                        action=action,
                        ts=time.time(),
                        value=True,
                    )
                )
            elif isinstance(elem, SliderElement):
                val: int | float = int(elem.value) if elem.integer else elem.value
                self._event_queue.append(
                    InteractionMessage(
                        element_id=elem.id,
                        action="changed",
                        ts=time.time(),
                        value=val,
                    )
                )
            elif isinstance(elem, CheckboxElement):
                self._event_queue.append(
                    InteractionMessage(
                        element_id=elem.id,
                        action="changed",
                        ts=time.time(),
                        value=elem.value,
                    )
                )
            elif isinstance(elem, ComboElement):
                item_text = (
                    elem.items[elem.selected]
                    if 0 <= elem.selected < len(elem.items)
                    else ""
                )
                self._event_queue.append(
                    InteractionMessage(
                        element_id=elem.id,
                        action="changed",
                        ts=time.time(),
                        value={"index": elem.selected, "item": item_text},
                    )
                )
            elif isinstance(elem, InputTextElement):
                self._event_queue.append(
                    InteractionMessage(
                        element_id=elem.id,
                        action="changed",
                        ts=time.time(),
                        value=elem.value,
                    )
                )
            elif isinstance(elem, RadioElement):
                item_text = (
                    elem.items[elem.selected]
                    if 0 <= elem.selected < len(elem.items)
                    else ""
                )
                self._event_queue.append(
                    InteractionMessage(
                        element_id=elem.id,
                        action="changed",
                        ts=time.time(),
                        value={"index": elem.selected, "item": item_text},
                    )
                )
            elif isinstance(elem, ColorPickerElement):
                self._event_queue.append(
                    InteractionMessage(
                        element_id=elem.id,
                        action="changed",
                        ts=time.time(),
                        value=elem.value,
                    )
                )
            elif isinstance(elem, SelectableElement):
                self._event_queue.append(
                    InteractionMessage(
                        element_id=elem.id,
                        action="clicked",
                        ts=time.time(),
                        value=not elem.selected,
                    )
                )

    # -- rendering ---------------------------------------------------------

    def _render_scene(self) -> None:
        from imgui_bundle import imgui

        imgui.get_style().font_scale_main = self._font_scale

        # Provide a viewport-wide dock space so manual imgui.begin() windows
        # can be dragged into tabbed dock nodes by the user.
        imgui.dock_space_over_viewport(
            flags=imgui.DockNodeFlags_.passthru_central_node.value,
        )

        # Always render the ambient flame as a background element.
        # Content renders on top of it.
        self._render_idle(imgui)

        # World menu: background click to toggle, floating panel.
        self._check_world_menu_background_click(imgui)
        self._render_world_panel(imgui)

        # Render framed scenes (DES-022 workspace model)
        self._render_frames(imgui)

        if not self._scenes:
            return

        if len(self._scenes) == 1:
            # Single scene: render directly without tab bar chrome
            scene_id = self._scene_order[0]
            self._render_scene_tab(scene_id)
            return

        # Multiple scenes: render closable tab bar
        if imgui.begin_tab_bar("##lux_scenes"):
            closed_tabs: list[str] = []
            for scene_id in list(self._scene_order):
                scene = self._scenes[scene_id]
                label = scene.title or scene_id
                closable = True
                selected, still_open = imgui.begin_tab_item(
                    f"{label}##{scene_id}", closable
                )
                if selected:
                    self._active_tab = scene_id
                    self._render_scene_tab(scene_id)
                    imgui.end_tab_item()
                if still_open is not None and not still_open:
                    closed_tabs.append(scene_id)
            imgui.end_tab_bar()
            for sid in closed_tabs:
                self._dismiss_scene(sid)

    # Cascade layout: each new frame offsets from the previous one.
    _CASCADE_BASE_X = 30.0
    _CASCADE_BASE_Y = 40.0
    _CASCADE_DX = 30.0
    _CASCADE_DY = 30.0
    _FRAME_FILL = 0.75

    _FLAG_MAP: ClassVar[dict[str, str]] = {
        "no_resize": "no_resize",
        "no_collapse": "no_collapse",
        "auto_resize": "always_auto_resize",
        "no_title_bar": "no_title_bar",
        "no_background": "no_background",
        "no_scrollbar": "no_scrollbar",
    }

    def _resolve_frame_flags(self, frame: _Frame, imgui: Any) -> int:
        """Map frame flag names to an ImGui window flags bitmask."""
        result = 0
        if not frame.flags:
            return result
        for key, enabled in frame.flags.items():
            if not enabled:
                continue
            attr = self._FLAG_MAP.get(key)
            if attr is None:
                continue
            flag = getattr(imgui.WindowFlags_, attr, None)
            if flag is not None:
                result |= flag.value
        return result

    _DOCK_BAR_HEIGHT = 28.0

    def _apply_fit_all(self) -> bool:
        """If fit-all was requested, restore all frames and compute tile layout.

        Returns True when fitting is active (callers should use
        ``Cond_.always`` for position/size).
        """
        if not self._fit_all_frames:
            return False
        self._fit_all_frames = False
        frames = list(self._frames.values())
        for f in frames:
            f.minimized = False
        return True

    @staticmethod
    def _compute_tile_layout(
        imgui: Any,
        region: Any,
        frames: list[_Frame],
    ) -> dict[str, tuple[float, float, float, float]]:
        """Compute tiled positions for frames that fill the content region.

        Returns a dict of frame_id → (x, y, w, h).  Frames are arranged
        in a grid with roughly equal-sized cells.
        """
        import math

        n = len(frames)
        if n == 0:
            return {}
        origin = imgui.get_cursor_screen_pos()
        cols = math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)
        gap = 4.0
        cell_w = (region.x - gap * (cols + 1)) / cols
        cell_h = (region.y - gap * (rows + 1)) / rows
        # Floor prevents zero/negative cells; frames may extend past the
        # viewport when the window is very small, but ImGui scroll handles it.
        cell_w = max(cell_w, 200.0)
        cell_h = max(cell_h, 150.0)
        result: dict[str, tuple[float, float, float, float]] = {}
        for i, f in enumerate(frames):
            col = i % cols
            row = i // cols
            x = origin.x + gap + col * (cell_w + gap)
            y = origin.y + gap + row * (cell_h + gap)
            result[f.frame_id] = (x, y, cell_w, cell_h)
        return result

    def _render_single_frame(
        self,
        frame: _Frame,
        imgui: Any,
        *,
        fitting: bool,
        tile_layout: dict[str, tuple[float, float, float, float]],
        default_size: tuple[float, float],
    ) -> tuple[str | None, bool]:
        """Render one frame window.

        Returns (result, hovered) where result is 'closed', 'minimized',
        or None, and hovered indicates the mouse is over this frame.
        """
        if fitting and frame.frame_id in tile_layout:
            cond = imgui.Cond_.always.value
            x, y, fw, fh = tile_layout[frame.frame_id]
        else:
            cond = imgui.Cond_.first_use_ever.value
            x = self._CASCADE_BASE_X + frame.cascade_index * self._CASCADE_DX
            y = self._CASCADE_BASE_Y + frame.cascade_index * self._CASCADE_DY
            fw = float(frame.initial_size[0]) if frame.initial_size else default_size[0]
            fh = float(frame.initial_size[1]) if frame.initial_size else default_size[1]
        imgui.set_next_window_pos((x, y), cond)
        imgui.set_next_window_size((fw, fh), cond)
        if self._focus_frame_id == frame.frame_id:
            imgui.set_next_window_focus()
            self._focus_frame_id = None
        win_flags = self._resolve_frame_flags(frame, imgui)
        still_open = True
        expanded, still_open = imgui.begin(
            f"{frame.title}##{frame.frame_id}", still_open, win_flags
        )
        hovered = imgui.is_window_hovered(
            imgui.HoveredFlags_.root_and_child_windows.value
        )
        if not still_open:
            imgui.end()
            return "closed", hovered
        if not expanded:
            # Collapse triangle clicked — minimize to dock bar.
            # Skip when docked: ImGui reports expanded=False during
            # docking transitions.
            if not imgui.is_window_docked():
                imgui.set_window_collapsed(False)
                imgui.end()
                return "minimized", hovered
            imgui.end()
            return None, hovered
        self._render_frame_contents(frame, imgui)
        imgui.end()
        return None, hovered

    def _render_frames(self, imgui: Any) -> None:
        """Render each frame as an ImGui inner window."""
        # Default frame size: 75% of content region (first use only).
        region = imgui.get_content_region_avail()
        frame_w = max(400.0, region.x * self._FRAME_FILL)
        frame_h = max(300.0, region.y * self._FRAME_FILL)

        fitting = self._apply_fit_all()
        tile_layout: dict[str, tuple[float, float, float, float]] = {}
        if fitting:
            tile_layout = self._compute_tile_layout(
                imgui, region, list(self._frames.values())
            )

        closed_frames: list[str] = []
        minimized_frames: list[str] = []
        any_frame_hovered = False
        for frame in list(self._frames.values()):
            if frame.minimized:
                continue
            result, hovered = self._render_single_frame(
                frame,
                imgui,
                fitting=fitting,
                tile_layout=tile_layout,
                default_size=(frame_w, frame_h),
            )
            any_frame_hovered = any_frame_hovered or hovered
            if result == "closed":
                closed_frames.append(frame.frame_id)
            elif result == "minimized":
                minimized_frames.append(frame.frame_id)
        for fid in closed_frames:
            self._close_frame(fid)
        for fid in minimized_frames:
            self._frames[fid].minimized = True
        # Dock bar for minimized frames
        self._render_dock_bar(imgui, any_frame_hovered=any_frame_hovered)

    def _render_dock_bar(self, imgui: Any, *, any_frame_hovered: bool = False) -> None:
        """Render a bottom dock bar showing minimized frames as pills.

        *any_frame_hovered* is True when the mouse is over a visible frame
        window.  When set, pill clicks are suppressed to prevent restoring
        a frame when the user clicks on a frame that overlaps the dock bar.
        """
        minimized = [f for f in self._frames.values() if f.minimized]
        if not minimized:
            return

        from imgui_bundle import ImVec2

        viewport = imgui.get_main_viewport()
        bar_h = self._DOCK_BAR_HEIGHT
        bar_y = viewport.pos.y + viewport.size.y - bar_h
        bar_x = viewport.pos.x
        bar_w = viewport.size.x

        # Draw bar background on the foreground draw list so it's
        # always visible regardless of window stacking.
        draw = imgui.get_foreground_draw_list()
        style = imgui.get_style()

        # Derive colors from the active theme.
        bar_bg = imgui.get_color_u32(style.color_(imgui.Col_.title_bg))
        border_col = imgui.get_color_u32(style.color_(imgui.Col_.border))
        text_col = imgui.get_color_u32(style.color_(imgui.Col_.text))

        draw.add_rect_filled(
            ImVec2(bar_x, bar_y),
            ImVec2(bar_x + bar_w, bar_y + bar_h),
            bar_bg,
        )
        draw.add_line(
            ImVec2(bar_x, bar_y),
            ImVec2(bar_x + bar_w, bar_y),
            border_col,
            1.0,
        )

        # Pill layout — use raw mouse hit-testing instead of an invisible
        # ImGui window.  The dock bar renders on the foreground draw list
        # which has no window in the z-order, so invisible_button widgets
        # inside a helper window never receive clicks reliably.
        pill_pad = 6.0
        pill_h = bar_h - pill_pad * 2.0
        pill_x = bar_x + pill_pad
        pill_y = bar_y + pill_pad
        pill_gap = 4.0
        max_x = bar_x + bar_w - pill_pad

        pill_normal = imgui.get_color_u32(style.color_(imgui.Col_.button))
        pill_hovered = imgui.get_color_u32(style.color_(imgui.Col_.button_hovered))

        mouse = imgui.get_mouse_pos()
        # Accept clicks when no frame window or ImGui item is under the
        # cursor.  The previous is_window_hovered(any_window) guard was
        # always true because dock_space_over_viewport covers the entire
        # viewport, blocking all pill clicks.  We now use the explicit
        # any_frame_hovered flag computed during frame rendering.
        clicked = (
            imgui.is_mouse_clicked(imgui.MouseButton_.left)
            and not imgui.is_any_item_hovered()
            and not any_frame_hovered
        )

        for frame in minimized:
            text_size = imgui.calc_text_size(frame.title)
            pill_w = text_size.x + 16.0

            # Truncate: if this pill would overflow, show ellipsis.
            if pill_x + pill_w > max_x:
                ellipsis_size = imgui.calc_text_size("...")
                ey = pill_y + (pill_h - ellipsis_size.y) * 0.5
                draw.add_text(ImVec2(pill_x, ey), text_col, "...")
                break

            p_min = ImVec2(pill_x, pill_y)
            p_max = ImVec2(pill_x + pill_w, pill_y + pill_h)

            # Raw hit-test: is the mouse inside this pill rect?
            hovered = p_min.x <= mouse.x <= p_max.x and p_min.y <= mouse.y <= p_max.y

            bg = pill_hovered if hovered else pill_normal
            draw.add_rect_filled(p_min, p_max, bg, 4.0)

            text_y = pill_y + (pill_h - text_size.y) * 0.5
            draw.add_text(ImVec2(pill_x + 8.0, text_y), text_col, frame.title)

            if hovered and clicked:
                frame.minimized = False
                self._focus_frame_id = frame.frame_id

            pill_x += pill_w + pill_gap

    def _render_frame_contents(self, frame: _Frame, imgui: Any) -> None:
        """Render scenes inside a frame.

        Layout modes:
        - ``"tab"`` (default): multiple scenes as tabs, one visible at a time.
        - ``"stack"``: all scenes stacked vertically with collapsing headers.
        """
        if not frame.scenes:
            return
        if len(frame.scenes) == 1:
            scene_id = frame.scene_order[0]
            self._render_framed_scene(frame, scene_id)
            return
        if frame.layout == "stack":
            self._render_frame_stack(frame, imgui)
        else:
            self._render_frame_tabs(frame, imgui)

    def _render_frame_tabs(self, frame: _Frame, imgui: Any) -> None:
        """Render multi-scene frame as tabs."""
        if imgui.begin_tab_bar(f"##frame_tabs_{frame.frame_id}"):
            closed_tabs: list[str] = []
            for scene_id in list(frame.scene_order):
                scene = frame.scenes[scene_id]
                label = scene.title or scene_id
                closable = True
                selected, tab_open = imgui.begin_tab_item(
                    f"{label}##{scene_id}", closable
                )
                if selected:
                    frame.active_tab = scene_id
                    self._render_framed_scene(frame, scene_id)
                    imgui.end_tab_item()
                if tab_open is not None and not tab_open:
                    closed_tabs.append(scene_id)
            imgui.end_tab_bar()
            for sid in closed_tabs:
                self._dismiss_framed_scene(frame, sid)

    def _render_frame_stack(self, frame: _Frame, imgui: Any) -> None:
        """Render multi-scene frame as vertically stacked collapsing headers.

        Unlike tab layout, stack layout has no per-scene close affordance.
        Scenes represent live data feeds (e.g. per-repo status) and are
        managed programmatically, not dismissed by the user.
        """
        for scene_id in list(frame.scene_order):
            scene = frame.scenes[scene_id]
            label = scene.title or scene_id
            flags = imgui.TreeNodeFlags_.default_open.value
            if imgui.collapsing_header(f"{label}##{scene_id}", flags=flags):
                imgui.push_id(scene_id)
                self._render_framed_scene(frame, scene_id)
                imgui.pop_id()

    def _render_framed_scene(self, frame: _Frame, scene_id: str) -> None:
        """Render a scene's elements inside a frame."""
        self._widget_state = self._scene_widget_state[scene_id]
        self._render_fn_state = self._scene_render_fn_state[scene_id]
        scene = frame.scenes[scene_id]
        for elem in scene.elements:
            self._render_element(elem)

    def _close_frame(self, frame_id: str, *, notify: bool = True) -> None:
        """Remove a frame and all its scenes.

        When *notify* is True, a ``frame_close`` event is sent to all
        contributing clients (``owner_fds``).  Used for user-initiated
        close and tab close.  When False, no events are emitted — used
        during disconnect cleanup where the departing client's fd is
        already removed and surviving clients should not be notified.
        """
        frame = self._frames.pop(frame_id, None)
        if frame is None:
            return
        if self._focus_frame_id == frame_id:
            self._focus_frame_id = None
        # Drain stale events for elements in the removed scenes
        removed_ids: set[str] = set()
        for scene_id in frame.scene_order:
            scene = frame.scenes.get(scene_id)
            if scene is not None:
                for elem in scene.elements:
                    removed_ids.update(_collect_ids(elem))
            self._scene_widget_state.pop(scene_id, None)
            self._scene_render_fn_state.pop(scene_id, None)
            self._scene_to_frame.pop(scene_id, None)
            self._scene_to_owner.pop(scene_id, None)
        if removed_ids:
            self._event_queue = [
                ev for ev in self._event_queue if ev.element_id not in removed_ids
            ]
        if notify:
            close_event = InteractionMessage(
                element_id=frame_id,
                action="frame_close",
                ts=time.time(),
            )
            for ofd in frame.owner_fds:
                owner_sock = self._fd_to_client.get(ofd)
                if owner_sock is not None:
                    self._send_to_client(owner_sock, close_event)

    def _dismiss_framed_scene(
        self, frame: _Frame, scene_id: str, *, notify: bool = True
    ) -> None:
        """Remove a single scene from a frame."""
        dismissed = frame.scenes.pop(scene_id, None)
        if dismissed is not None:
            dismissed_ids: set[str] = set()
            for elem in dismissed.elements:
                dismissed_ids.update(_collect_ids(elem))
            if dismissed_ids:
                self._event_queue = [
                    ev for ev in self._event_queue if ev.element_id not in dismissed_ids
                ]
        frame.scene_order = [s for s in frame.scene_order if s != scene_id]
        self._scene_widget_state.pop(scene_id, None)
        self._scene_render_fn_state.pop(scene_id, None)
        self._scene_to_frame.pop(scene_id, None)
        self._scene_to_owner.pop(scene_id, None)
        if frame.active_tab == scene_id:
            frame.active_tab = frame.scene_order[0] if frame.scene_order else None
        if not frame.scenes:
            self._close_frame(frame.frame_id, notify=notify)

    def _render_scene_tab(self, scene_id: str) -> None:
        """Render a single scene's elements with its own widget state."""
        self._widget_state = self._scene_widget_state[scene_id]
        self._render_fn_state = self._scene_render_fn_state[scene_id]
        scene = self._scenes[scene_id]
        if scene.title and len(self._scenes) == 1:
            from imgui_bundle import imgui

            imgui.separator_text(scene.title)
        for elem in scene.elements:
            self._render_element(elem)

    @staticmethod
    def _render_idle(imgui: Any) -> None:
        """Render an ambient idle screen with radial light rays and flame.

        Always called — the flame persists as a background element
        whether content is present or not.  Frames and scenes render
        on top since they are separate ImGui windows.
        """
        import math

        from imgui_bundle import ImVec2, ImVec4

        t = time.time()
        region = imgui.get_content_region_avail()
        origin = imgui.get_cursor_screen_pos()
        draw = imgui.get_window_draw_list()

        # Detect light vs dark theme from window background luminance
        bg = imgui.get_style_color_vec4(imgui.Col_.window_bg)
        bg_lum = bg.x * 0.299 + bg.y * 0.587 + bg.z * 0.114
        is_light = bg_lum > 0.5

        # -- radial light rays from center --
        cx = origin.x + region.x * 0.5
        cy = origin.y + region.y * 0.5
        max_radius = math.sqrt(region.x**2 + region.y**2) * 0.5
        num_rays = 48
        # Rays rotate very slowly with pauses
        rot_phase = math.sin(t * 0.15)
        rotation = rot_phase * rot_phase * rot_phase * 0.3  # radians, ±0.3
        # Breathing modulates ray alpha
        breath_raw = math.sin(t * 0.8)
        ray_breath = max(breath_raw, 0.0) ** 0.6
        for i in range(num_rays):
            angle = (i / num_rays) * math.tau + rotation
            # Vary ray length and alpha for organic feel
            length_var = 0.6 + 0.4 * math.sin(angle * 3.0 + t * 0.2)
            ray_len = max_radius * length_var
            # Inner point (near flame, start offset to not overdraw flame)
            inner_r = 25.0
            ix = cx + math.cos(angle) * inner_r
            iy = cy + math.sin(angle) * inner_r
            # Outer point
            ox = cx + math.cos(angle) * ray_len
            oy = cy + math.sin(angle) * ray_len
            ray_alpha = (0.015 + 0.01 * ray_breath) * length_var
            # Dark theme: warm white rays; light theme: darker, more opaque rays
            if is_light:
                ray_col = imgui.get_color_u32(ImVec4(0.7, 0.4, 0.1, ray_alpha * 8.0))
            else:
                ray_col = imgui.get_color_u32(ImVec4(1.0, 0.7, 0.3, ray_alpha))
            draw.add_line(ImVec2(ix, iy), ImVec2(ox, oy), ray_col, 1.0)

        # -- centered flame (cx, cy already set above) --
        breath = ray_breath  # reuse breathing from rays

        # Flame sway: gentle tip movement with pauses
        sway_phase = math.sin(t * 0.6)
        sway = sway_phase * sway_phase * sway_phase * 3.0  # ±3px, pauses at center
        # Secondary faster flicker for organic feel
        flicker = math.sin(t * 2.3) * 0.8 + math.sin(t * 3.7) * 0.4

        flame_h = 26.0 + 4.0 * breath  # flame height breathes
        flame_w = 10.0 + 1.5 * breath  # flame width breathes

        # Flame base center (bottom of flame)
        base_y = cy + 8.0
        tip_y = base_y - flame_h
        tip_x = cx + sway

        # -- outer glow (warm orange, very transparent) --
        glow_r = flame_w + 6.0
        glow_alpha = 0.06 + 0.03 * breath
        for i in range(3):
            r = glow_r + i * 4.0
            a = glow_alpha * (1.0 - i * 0.3)
            glow_col = imgui.get_color_u32(ImVec4(1.0, 0.6, 0.2, a))
            draw.add_circle_filled(ImVec2(cx, base_y - flame_h * 0.4), r, glow_col)

        # -- outer flame (deep orange) --
        _draw_flame_shape(
            draw,
            imgui,
            cx,
            base_y,
            tip_x,
            tip_y,
            flame_w,
            flame_h,
            r=1.0,
            g=0.45,
            b=0.1,
            alpha=0.35 + 0.1 * breath,
        )

        # -- middle flame (bright orange-yellow) --
        mid_w = flame_w * 0.65
        mid_h = flame_h * 0.75
        mid_tip_y = base_y - mid_h
        _draw_flame_shape(
            draw,
            imgui,
            cx,
            base_y,
            tip_x + flicker * 0.5,
            mid_tip_y,
            mid_w,
            mid_h,
            r=1.0,
            g=0.7,
            b=0.15,
            alpha=0.45 + 0.1 * breath,
        )

        # -- inner core (bright yellow-white) --
        core_w = flame_w * 0.3
        core_h = flame_h * 0.45
        core_tip_y = base_y - core_h
        _draw_flame_shape(
            draw,
            imgui,
            cx,
            base_y + 2,
            tip_x + flicker * 0.3,
            core_tip_y + 2,
            core_w,
            core_h,
            r=1.0,
            g=0.95,
            b=0.7,
            alpha=0.55 + 0.15 * breath,
        )

        # "Ready" label below the flame — uses theme text color at low alpha
        label_y = base_y + 10.0
        text = "Lux"
        text_size = imgui.calc_text_size(text)
        tc = imgui.get_style_color_vec4(imgui.Col_.text)
        text_color = imgui.get_color_u32(ImVec4(tc.x, tc.y, tc.z, 0.35))
        draw.add_text(ImVec2(cx - text_size.x * 0.5, label_y), text_color, text)

    def _dismiss_scene(self, scene_id: str) -> None:
        """Remove a scene and all its associated state."""
        old_order = self._scene_order
        old_idx = old_order.index(scene_id) if scene_id in old_order else -1
        dismissed = self._scenes.pop(scene_id, None)
        if dismissed is not None:
            # Collect IDs from dismissed scene
            dismissed_ids: set[str] = set()
            for elem in dismissed.elements:
                dismissed_ids.update(_collect_ids(elem))
                if isinstance(elem, WindowElement):
                    self._dirty_windows.discard(elem.id)
            # Keep events for IDs that still exist in remaining scenes
            surviving_ids: set[str] = set()
            for scene in self._scenes.values():
                for elem in scene.elements:
                    surviving_ids.update(_collect_ids(elem))
            stale_ids = dismissed_ids - surviving_ids
            self._event_queue = [
                ev for ev in self._event_queue if ev.element_id not in stale_ids
            ]
        self._scene_order = [s for s in old_order if s != scene_id]
        self._scene_widget_state.pop(scene_id, None)
        self._scene_render_fn_state.pop(scene_id, None)
        if self._active_tab == scene_id:
            if self._scene_order:
                # Select neighbor: next tab, or last if dismissed was rightmost
                new_idx = min(old_idx, len(self._scene_order) - 1)
                self._active_tab = self._scene_order[new_idx]
            else:
                self._active_tab = None

    _RENDERERS: ClassVar[dict[str, str]] = {
        "text": "_render_text",
        "button": "_render_button",
        "separator": "_render_separator",
        "image": "_render_image",
        "slider": "_render_slider",
        "checkbox": "_render_checkbox",
        "combo": "_render_combo",
        "input_text": "_render_input_text",
        "input_number": "_render_input_number",
        "radio": "_render_radio",
        "color_picker": "_render_color_picker",
        "draw": "_render_draw",
        "group": "_render_group",
        "tab_bar": "_render_tab_bar",
        "collapsing_header": "_render_collapsing_header",
        "window": "_render_window",
        "selectable": "_render_selectable",
        "tree": "_render_tree",
        "table": "_render_table",
        "plot": "_render_plot",
        "progress": "_render_progress",
        "spinner": "_render_spinner",
        "markdown": "_render_markdown",
        "render_function": "_render_render_function",
        "modal": "_render_modal",
    }

    def _render_element(self, elem: Element) -> None:
        from imgui_bundle import imgui

        method_name = self._RENDERERS.get(elem.kind)
        if method_name is not None:
            getattr(self, method_name)(elem)
        else:
            imgui.text(f"[unsupported element: {elem.kind}]")

        # Unstyled text with tooltip uses selectable() in _render_text_tooltip
        # and handles its own tooltip there.  All other elements (including
        # styled text) use this generic tooltip handler.
        is_text_with_inline_tooltip = (
            elem.kind == "text"
            and not getattr(elem, "style", None)
            and getattr(elem, "tooltip", None)
        )
        if not is_text_with_inline_tooltip:
            tooltip = getattr(elem, "tooltip", None)
            if tooltip and imgui.is_item_hovered(imgui.HoveredFlags_.for_tooltip.value):
                imgui.set_tooltip(tooltip)

    @staticmethod
    def _parse_hex_color(hex_str: str) -> tuple[float, float, float, float] | None:
        """Parse "#RRGGBB" or "#RRGGBBAA" to (r, g, b, a) floats."""
        s = hex_str.lstrip("#")
        try:
            if len(s) == 6:
                r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
                return (r / 255.0, g / 255.0, b / 255.0, 1.0)
            if len(s) == 8:
                r = int(s[0:2], 16)
                g, b, a = int(s[2:4], 16), int(s[4:6], 16), int(s[6:8], 16)
                return (r / 255.0, g / 255.0, b / 255.0, a / 255.0)
        except ValueError:
            return None
        return None

    @staticmethod
    def _render_text_tooltip(
        text_elem: Any,
        content: str,
        color: tuple[float, float, float, float] | None,
    ) -> None:
        """Render a text element with tooltip via selectable().

        selectable() is hoverable — imgui.text() is not. Tooltip is
        handled here (not in the generic _render_element handler) to
        avoid first-item-after-collapsing-header hover detection issues.
        """
        from imgui_bundle import ImVec4, imgui

        eid = getattr(text_elem, "id", "t")
        if color:
            imgui.push_style_color(imgui.Col_.text.value, ImVec4(*color))
        try:
            selected = False
            imgui.selectable(f"{content}##{eid}", selected)
        finally:
            if color:
                imgui.pop_style_color()
        if imgui.is_item_hovered(imgui.HoveredFlags_.for_tooltip.value):
            imgui.set_tooltip(text_elem.tooltip)

    def _render_text(self, elem: Element) -> None:
        from imgui_bundle import ImVec4, imgui

        text_elem: Any = elem
        content: str = text_elem.content
        style: str | None = text_elem.style
        has_tooltip = bool(getattr(text_elem, "tooltip", None))
        color_str: str | None = getattr(text_elem, "color", None)
        color = self._parse_hex_color(color_str) if color_str else None

        # For unstyled text with a tooltip, use selectable() for hover.
        # Styled text handles tooltips via the generic post-render block.
        if has_tooltip and not style:
            self._render_text_tooltip(text_elem, content, color)
            return

        if color:
            imgui.push_style_color(imgui.Col_.text.value, ImVec4(*color))
        try:
            if style == "heading":
                imgui.separator_text(content)
            elif style == "caption":
                if not color:
                    imgui.push_style_color(
                        imgui.Col_.text.value, ImVec4(0.6, 0.6, 0.6, 1.0)
                    )
                try:
                    imgui.text_wrapped(content)
                finally:
                    if not color:
                        imgui.pop_style_color()
            elif style == "code":
                imgui.indent(10.0)
                imgui.text(content)
                imgui.unindent(10.0)
            else:
                imgui.text_wrapped(content)
        finally:
            if color:
                imgui.pop_style_color()

    _arrow_dirs: ClassVar[dict[str, Any] | None] = None

    def _resolve_arrow_dir(self, name: str) -> Any | None:
        from imgui_bundle import imgui

        if DisplayServer._arrow_dirs is None:
            DisplayServer._arrow_dirs = {
                "left": imgui.Dir.left,
                "right": imgui.Dir.right,
                "up": imgui.Dir.up,
                "down": imgui.Dir.down,
            }
        return DisplayServer._arrow_dirs.get(name)

    def _render_button(self, elem: Element) -> None:
        from imgui_bundle import imgui

        btn: Any = elem
        label: str = btn.label
        eid: str = btn.id
        action: str = btn.action or eid
        disabled: bool = btn.disabled
        arrow: str | None = btn.arrow
        small: bool = btn.small

        if disabled:
            imgui.begin_disabled()

        clicked = False
        if arrow:
            direction = self._resolve_arrow_dir(arrow)
            if direction is not None:
                clicked = imgui.arrow_button(f"##{eid}", direction)
            else:
                logger.warning("Unknown arrow direction %r for %s", arrow, eid)
                clicked = imgui.button(f"{label}##{eid}")
        elif small:
            clicked = imgui.small_button(f"{label}##{eid}")
        else:
            clicked = imgui.button(f"{label}##{eid}")

        if clicked:
            self._event_queue.append(
                InteractionMessage(
                    element_id=eid,
                    action=action,
                    ts=time.time(),
                    value=True,
                )
            )

        if disabled:
            imgui.end_disabled()

    def _render_separator(self, _elem: Element) -> None:
        from imgui_bundle import imgui

        imgui.separator()

    def _render_image(self, elem: Element) -> None:
        from imgui_bundle import ImVec2, imgui

        img: Any = elem
        path: str | None = img.path
        width: int = img.width if img.width is not None else 200
        height: int = img.height if img.height is not None else 150

        tex_id = self._textures.get_or_load(path) if path else None
        if tex_id is not None:
            imgui.image(imgui.ImTextureRef(tex_id), ImVec2(width, height))
        else:
            alt: str = img.alt or path or "(image)"
            imgui.text(f"[{alt}]")

    def _render_slider(self, elem: Element) -> None:
        from imgui_bundle import imgui

        sl: Any = elem
        eid: str = sl.id
        label: str = sl.label
        v_min: float = sl.min
        v_max: float = sl.max
        fmt: str = sl.format
        is_int: bool = sl.integer

        current = self._widget_state.ensure(eid, sl.value)

        new_val: int | float
        if is_int:
            changed, new_val = imgui.slider_int(
                f"{label}##{eid}", int(current), int(v_min), int(v_max)
            )
        else:
            changed, new_val = imgui.slider_float(
                f"{label}##{eid}", float(current), float(v_min), float(v_max), fmt
            )

        if changed:
            self._widget_state.set(eid, new_val)
            self._event_queue.append(
                InteractionMessage(
                    element_id=eid,
                    action="changed",
                    ts=time.time(),
                    value=new_val,
                )
            )

    def _render_checkbox(self, elem: Element) -> None:
        from imgui_bundle import imgui

        cb: Any = elem
        eid: str = cb.id
        label: str = cb.label

        current = self._widget_state.ensure(eid, cb.value)
        changed, new_val = imgui.checkbox(f"{label}##{eid}", current)
        if changed:
            self._widget_state.set(eid, new_val)
            self._event_queue.append(
                InteractionMessage(
                    element_id=eid,
                    action="changed",
                    ts=time.time(),
                    value=new_val,
                )
            )

    def _render_combo(self, elem: Element) -> None:
        from imgui_bundle import imgui

        co: Any = elem
        eid: str = co.id
        label: str = co.label
        items: list[str] = co.items

        initial = max(0, min(co.selected, len(items) - 1)) if items else 0
        current = self._widget_state.ensure(eid, initial)
        if not items:
            imgui.text(f"{label}: (empty)")
            return
        if current < 0 or current >= len(items):
            current = 0
            self._widget_state.set(eid, current)
        changed, new_val = imgui.combo(f"{label}##{eid}", current, items)
        if changed:
            self._widget_state.set(eid, new_val)
            item_text = items[new_val] if 0 <= new_val < len(items) else ""
            self._event_queue.append(
                InteractionMessage(
                    element_id=eid,
                    action="changed",
                    ts=time.time(),
                    value={"index": new_val, "item": item_text},
                )
            )

    def _render_input_text(self, elem: Element) -> None:
        from imgui_bundle import imgui

        it: Any = elem
        eid: str = it.id
        label: str = it.label
        hint: str = it.hint

        current = self._widget_state.ensure(eid, it.value)

        if hint:
            changed, new_val = imgui.input_text_with_hint(
                f"{label}##{eid}", hint, current
            )
        else:
            changed, new_val = imgui.input_text(f"{label}##{eid}", current)

        if changed:
            self._widget_state.set(eid, new_val)
            self._event_queue.append(
                InteractionMessage(
                    element_id=eid,
                    action="changed",
                    ts=time.time(),
                    value=new_val,
                )
            )

    def _render_input_number(self, elem: Element) -> None:
        from imgui_bundle import imgui

        el: Any = elem
        eid: str = el.id
        label: str = el.label
        is_int: bool = el.integer
        step: float | None = el.step
        fmt: str = el.format

        initial: int | float = el.value
        if el.min is not None and initial < el.min:
            initial = int(el.min) if is_int else el.min
        if el.max is not None and initial > el.max:
            initial = int(el.max) if is_int else el.max
        current = self._widget_state.ensure(eid, initial)

        result: int | float
        if is_int:
            s = int(step) if step is not None else 0
            changed, result = imgui.input_int(
                f"{label}##{eid}", int(current), s, s * 10
            )
        else:
            s_f = step if step is not None else 0.0
            changed, result = imgui.input_float(
                f"{label}##{eid}", float(current), s_f, s_f * 10.0, fmt
            )

        if el.min is not None and result < el.min:
            result = int(el.min) if is_int else el.min
            changed = True
        if el.max is not None and result > el.max:
            result = int(el.max) if is_int else el.max
            changed = True

        if changed:
            self._widget_state.set(eid, result)
            self._event_queue.append(
                InteractionMessage(
                    element_id=eid,
                    action="changed",
                    ts=time.time(),
                    value=result,
                )
            )

    def _render_radio(self, elem: Element) -> None:
        from imgui_bundle import imgui

        rd: Any = elem
        eid: str = rd.id
        label: str = rd.label
        items: list[str] = rd.items

        current: int = self._widget_state.ensure(eid, rd.selected)

        if label:
            imgui.text(label)

        for i, item in enumerate(items):
            if imgui.radio_button(f"{item}##{eid}_{i}", current == i) and current != i:
                self._widget_state.set(eid, i)
                self._event_queue.append(
                    InteractionMessage(
                        element_id=eid,
                        action="changed",
                        ts=time.time(),
                        value={"index": i, "item": item},
                    )
                )
                current = i
            if i < len(items) - 1:
                imgui.same_line()

    def _render_color_picker(self, elem: Element) -> None:
        from imgui_bundle import ImVec4, imgui

        cp: Any = elem
        eid: str = cp.id
        label: str = cp.label
        hex_str: str = cp.value
        use_alpha: bool = cp.alpha
        use_picker: bool = cp.picker

        r, g, b, a = _parse_color(hex_str)
        initial = ImVec4(r / 255.0, g / 255.0, b / 255.0, a / 255.0)
        current = self._widget_state.ensure(eid, initial)

        if use_picker:
            if use_alpha:
                changed, new_color = imgui.color_picker4(f"{label}##{eid}", current)
            else:
                changed, new_color = imgui.color_picker3(f"{label}##{eid}", current)
        elif use_alpha:
            changed, new_color = imgui.color_edit4(f"{label}##{eid}", current)
        else:
            changed, new_color = imgui.color_edit3(f"{label}##{eid}", current)

        if changed:
            self._widget_state.set(eid, new_color)
            if use_alpha:
                nc = new_color
                r_ = int(max(0.0, min(1.0, nc[0])) * 255)
                g_ = int(max(0.0, min(1.0, nc[1])) * 255)
                b_ = int(max(0.0, min(1.0, nc[2])) * 255)
                a_ = int(max(0.0, min(1.0, nc[3])) * 255)
                hex_val = f"#{r_:02X}{g_:02X}{b_:02X}{a_:02X}"
            else:
                hex_val = _color_to_hex(new_color[0], new_color[1], new_color[2])
            self._event_queue.append(
                InteractionMessage(
                    element_id=eid,
                    action="changed",
                    ts=time.time(),
                    value=hex_val,
                )
            )

    # -- container rendering -----------------------------------------------

    def _render_group(self, elem: Element) -> None:
        from imgui_bundle import imgui

        grp = cast("GroupElement", elem)
        layout = grp.layout

        if layout == "paged":
            self._render_paged_group(grp)
            return

        for i, child in enumerate(grp.children):
            if layout == "columns" and i > 0:
                imgui.same_line()
            self._render_element(child)

    def _paged_group_state_key(self, grp_id: str, page_source: str | None) -> str:
        """Return the widget_state key for a paged group's page index."""
        return page_source if page_source else f"{grp_id}__pg_idx"

    def _paged_group_read_index(self, state_key: str, total: int) -> int:
        """Read and clamp the current page index from widget_state."""
        raw = self._widget_state.get(state_key)
        page_idx = raw if isinstance(raw, int) else 0
        return max(0, min(page_idx, total - 1)) if total else 0

    def _render_paged_group(self, grp: Any) -> None:
        """Render a paged group with built-in Prev/Next navigation.

        Renders a nav row (Prev button, combo, Next button) followed by
        any non-combo children, then the active page.  The Prev/Next
        buttons modify widget_state directly — no round-trip.
        """
        from imgui_bundle import imgui

        pages = grp.pages
        total = len(pages) if pages else 0
        page_source: str | None = grp.page_source
        state_key = self._paged_group_state_key(grp.id, page_source)
        page_idx = self._paged_group_read_index(state_key, total)

        # Nav row: << Prev | [combo] | Next >>
        if imgui.button(f"<< Prev##{grp.id}_prev") and page_idx > 0:
            page_idx -= 1
            self._widget_state.set(state_key, page_idx)
        imgui.same_line()

        # Render the combo (from page_source) inline; other children after.
        other_children: list[Any] = []
        for child in grp.children:
            if page_source and getattr(child, "id", None) == page_source:
                self._render_element(child)
                imgui.same_line()
            else:
                other_children.append(child)

        if imgui.button(f"Next >>##{grp.id}_next") and page_idx < total - 1:
            page_idx += 1
            self._widget_state.set(state_key, page_idx)

        # Re-read after all interactions (Prev, combo change, Next) so the
        # page content always reflects the final widget_state value.
        page_idx = self._paged_group_read_index(state_key, total)

        for child in other_children:
            self._render_element(child)

        if pages and 0 <= page_idx < total:
            for child in pages[page_idx]:
                self._render_element(child)

    def _render_tab_bar(self, elem: Element) -> None:
        from imgui_bundle import imgui

        tb = cast("TabBarElement", elem)
        if imgui.begin_tab_bar(f"##{tb.id}"):
            for tab in tb.tabs:
                tab_label: str = tab.get("label", "Tab")
                if imgui.begin_tab_item(tab_label)[0]:
                    for child in tab.get("children", []):
                        self._render_element(child)
                    imgui.end_tab_item()
            imgui.end_tab_bar()

    def _render_collapsing_header(self, elem: Element) -> None:
        from imgui_bundle import imgui

        ch = cast("CollapsingHeaderElement", elem)
        flags = imgui.TreeNodeFlags_.default_open.value if ch.default_open else 0
        if imgui.collapsing_header(f"{ch.label}##{ch.id}", flags=flags):
            for child in ch.children:
                self._render_element(child)

    def _render_window(self, elem: Element) -> None:
        from imgui_bundle import imgui

        win = cast("WindowElement", elem)
        flags = 0
        if win.no_move:
            flags |= imgui.WindowFlags_.no_move.value
        if win.no_resize:
            flags |= imgui.WindowFlags_.no_resize.value
        if win.no_collapse:
            flags |= imgui.WindowFlags_.no_collapse.value
        if win.no_title_bar:
            flags |= imgui.WindowFlags_.no_title_bar.value
        if win.no_scrollbar:
            flags |= imgui.WindowFlags_.no_scrollbar.value
        if win.auto_resize:
            flags |= imgui.WindowFlags_.always_auto_resize.value

        if win.id in self._dirty_windows:
            cond = imgui.Cond_.always.value
            self._dirty_windows.discard(win.id)
        else:
            cond = imgui.Cond_.first_use_ever.value
        imgui.set_next_window_pos((win.x, win.y), cond)
        imgui.set_next_window_size((win.width, win.height), cond)

        title = win.title or win.id
        expanded, _ = imgui.begin(f"{title}##{win.id}", flags=flags)
        if expanded:
            for child in win.children:
                self._render_element(child)
        imgui.end()

    # -- selectable and tree rendering -------------------------------------

    def _render_selectable(self, elem: Element) -> None:
        from imgui_bundle import imgui

        sel: Any = elem
        eid: str = sel.id
        label: str = sel.label

        current: bool = self._widget_state.ensure(eid, sel.selected)
        clicked, new_val = imgui.selectable(f"{label}##{eid}", current)
        if clicked:
            self._widget_state.set(eid, new_val)
            self._event_queue.append(
                InteractionMessage(
                    element_id=eid,
                    action="clicked",
                    ts=time.time(),
                    value=new_val,
                )
            )

    def _render_tree(self, elem: Element) -> None:
        from imgui_bundle import imgui

        tree: Any = elem
        eid: str = tree.id
        label: str = tree.label
        nodes: list[dict[str, Any]] = tree.nodes

        flat: bool = getattr(tree, "flat", False)

        if label:
            imgui.text(label)
        for i, node in enumerate(nodes):
            self._render_tree_node(node, f"{eid}_{i}", eid, flat=flat)

    def _render_tree_node(
        self,
        node: dict[str, Any],
        node_id: str,
        tree_id: str,
        *,
        flat: bool = False,
    ) -> None:
        from imgui_bundle import imgui

        label: str = node.get("label", "")
        children: list[dict[str, Any]] = node.get("children", [])

        if children:
            if flat:
                no_push = imgui.TreeNodeFlags_.no_tree_push_on_open.value
                opened = imgui.tree_node_ex(f"{label}##{node_id}", no_push)
            else:
                opened = imgui.tree_node(f"{label}##{node_id}")
            if imgui.is_item_clicked():
                self._emit_node_click(tree_id, node_id, label)
            if opened:
                for i, child in enumerate(children):
                    self._render_tree_node(child, f"{node_id}_{i}", tree_id, flat=flat)
                if not flat:
                    imgui.tree_pop()
        else:
            if flat:
                selected = False
                clicked, _ = imgui.selectable(f"{label}##{node_id}", selected)
                if clicked:
                    self._emit_node_click(tree_id, node_id, label)
            else:
                leaf = imgui.TreeNodeFlags_.leaf.value
                no_push = imgui.TreeNodeFlags_.no_tree_push_on_open.value
                flags = leaf | no_push
                imgui.tree_node_ex(f"{label}##{node_id}", flags)
                if imgui.is_item_clicked():
                    self._emit_node_click(tree_id, node_id, label)

    def _emit_node_click(self, tree_id: str, node_id: str, label: str) -> None:
        self._event_queue.append(
            InteractionMessage(
                element_id=tree_id,
                action="node_clicked",
                ts=time.time(),
                value={"node_id": node_id, "label": label},
            )
        )

    # -- table rendering ---------------------------------------------------

    def _render_table(self, elem: Element) -> None:
        from imgui_bundle import imgui

        tbl: Any = elem
        eid: str = tbl.id
        columns: list[str] = tbl.columns
        rows: list[list[Any]] = tbl.rows
        flags_list: list[str] = tbl.flags
        filters: list[Any] | None = tbl.filters
        detail: Any | None = tbl.detail
        has_detail = detail is not None

        num_cols = len(columns)
        if num_cols == 0:
            return

        # Render built-in filters and get visible rows with indices
        indexed_rows, filters_changed = _apply_table_filters(
            filters,
            rows,
            eid,
            self._widget_state,
            imgui,
        )

        table_flags, copy_id = _parse_table_flags(flags_list, imgui)

        # Cache column weights — recompute when rows object or widths change.
        # id(rows) changes on update() since _apply_patch_set creates a new list.
        weight_cache_key = f"__tbl_wcache_{eid}"
        cached = self._widget_state.get(weight_cache_key)
        rows_id = id(rows)
        cw_sig = tuple(tbl.column_widths) if tbl.column_widths else None
        if cached is not None and cached[0] == rows_id and cached[1] == cw_sig:
            weights = cached[2]
        else:
            weights = _table_column_weights(columns, rows, tbl.column_widths)
            self._widget_state.set(weight_cache_key, (rows_id, cw_sig, weights))

        scene_id = self._active_tab or ""
        imgui_id = f"##{scene_id}/{eid}"
        sel_key = f"__tbl_sel_{eid}"
        page_key = f"__tbl_page_{eid}"

        # Reset page to 0 when filters change
        if filters_changed:
            self._widget_state.set(page_key, 0)

        # Paginate — slice visible rows to current page
        start, end, page_changed = _render_table_pagination(
            len(indexed_rows),
            eid,
            self._widget_state,
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

            selected_orig, row_clicked = _render_table_rows(
                page_rows,
                num_cols,
                selectable=has_detail or copy_id,
                table_id=eid,
                widget_state=self._widget_state,
                sel_key=sel_key,
                imgui=imgui,
            )
            imgui.end_table()

        else:
            selected_orig = self._widget_state.ensure(sel_key, -1)
            row_clicked = False

        # Keyboard navigation — up/down arrows move selection
        if has_detail:
            selected_orig = _handle_table_keyboard_nav(
                page_rows,
                selected_orig,
                sel_key,
                self._widget_state,
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
            self._event_queue.append(
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

        if has_detail and selected_orig >= 0:
            tbl_row = rows[selected_orig] if selected_orig < len(rows) else None
            _render_table_detail(
                detail,
                selected_orig,
                eid,
                imgui,
                table_row=tbl_row,
            )

    # -- plot rendering ----------------------------------------------------

    def _render_plot(self, elem: Element) -> None:
        from imgui_bundle import ImVec2, implot

        plt: Any = elem
        eid: str = plt.id
        title: str = plt.title
        plot_title = title if "##" in title else f"{title}##{eid}"

        if implot.begin_plot(plot_title, ImVec2(plt.width, plt.height)):
            if plt.x_label or plt.y_label:
                implot.setup_axes(plt.x_label or "", plt.y_label or "")

            for series in plt.series:
                s_label: str = series.get("label", "data")
                s_type: str = series.get("type", "line")
                x_data = np.array(series.get("x", []), dtype=np.float64)
                y_data = np.array(series.get("y", []), dtype=np.float64)

                if len(x_data) == 0 or len(y_data) == 0:
                    continue

                if s_type == "line":
                    implot.plot_line(s_label, x_data, y_data)
                elif s_type == "scatter":
                    implot.plot_scatter(s_label, x_data, y_data)
                elif s_type == "bar":
                    try:
                        implot.plot_bars(s_label, x_data, y_data, 0.67)
                    except TypeError:
                        implot.plot_bars(s_label, y_data, 0.67)

            implot.end_plot()

    # -- progress, spinner, markdown rendering ------------------------------

    def _render_progress(self, elem: Element) -> None:
        from imgui_bundle import ImVec2, imgui

        prog: Any = elem
        fraction: float = prog.fraction
        label: str = prog.label
        overlay = label if label else f"{int(fraction * 100)}%"
        imgui.progress_bar(fraction, ImVec2(-1, 0), overlay)

    def _render_spinner(self, elem: Element) -> None:
        from imgui_bundle import imgui

        sp: Any = elem
        eid: str = sp.id
        label: str = sp.label
        radius: float = sp.radius
        color_hex: str = sp.color

        try:
            from imgui_bundle import imspinner

            r, g, b, _a = _parse_color(color_hex)
            from imgui_bundle import ImVec4

            color = ImVec4(r / 255.0, g / 255.0, b / 255.0, 1.0)
            im_color = imgui.ImColor(color)
            imspinner.spinner_ang_triple(
                f"##spin_{eid}",
                radius,
                radius * 0.6,
                radius * 0.3,
                2.5,
                im_color,
                im_color,
                im_color,
            )
        except ImportError:
            dots = "." * (int(imgui.get_time() * 3) % 4)
            imgui.text(f"[loading{dots}]")

        if label:
            imgui.same_line()
            imgui.text(label)

    def _render_markdown(self, elem: Element) -> None:
        md: Any = elem
        try:
            from imgui_bundle import imgui, imgui_md

            imgui.push_text_wrap_pos(0.0)
            try:
                imgui_md.render_unindented(md.content)
            finally:
                imgui.pop_text_wrap_pos()
        except ImportError:
            from imgui_bundle import imgui

            imgui.text_unformatted(md.content)

    # -- render_function element -------------------------------------------

    def _make_event_callback(
        self, eid: str
    ) -> Callable[[str, dict[str, Any] | None], None]:
        """Create an event callback that routes ctx.send() to the event queue."""

        def _cb(action: str, data: dict[str, Any] | None) -> None:
            self._event_queue.append(
                InteractionMessage(
                    element_id=eid,
                    action=action,
                    ts=time.time(),
                    value=data,
                )
            )

        return _cb

    def _render_render_function(self, elem: Element) -> None:
        from imgui_bundle import ImVec4, imgui

        from punt_lux.ast_check import check_source
        from punt_lux.consent import ConsentDialog, ConsentResult
        from punt_lux.runtime import CodeExecutor

        rf: Any = elem
        eid: str = rf.id
        source: str = rf.source

        # Get or create per-element state
        state = self._render_fn_state.get(eid)
        if state is None or state.source != source:
            old_executor = state.executor if state is not None else None
            warnings = check_source(source)
            state = _RenderFnState(
                source=source,
                dialog=ConsentDialog(source, warnings),
                executor=old_executor,  # preserve for hot_reload
            )
            self._render_fn_state[eid] = state

        # Phase 1: Consent pending
        if state.dialog is not None:
            result = state.dialog.draw()
            if result == ConsentResult.ALLOWED:
                state.dialog = None
                old: CodeExecutor | None = state.executor
                if old is not None:
                    state.executor = old.hot_reload(source)
                else:
                    state.executor = CodeExecutor(
                        source,
                        event_callback=self._make_event_callback(eid),
                    )
            elif result == ConsentResult.DENIED:
                state.dialog = None
                state.executor = None
                state.denied = True
            return

        # Phase 2: Denied
        if state.denied:
            imgui.text_colored(
                ImVec4(1.0, 0.4, 0.4, 1.0), f"[{eid}] Code execution denied"
            )
            return

        # Phase 3: Running (or errored)
        if state.executor is not None:
            executor: CodeExecutor = state.executor
            if executor.has_error:
                imgui.text_colored(
                    ImVec4(1.0, 0.3, 0.3, 1.0),
                    f"Error: {executor.error_message}",
                )
                return
            avail = imgui.get_content_region_avail()
            executor.render(imgui.get_io().delta_time, avail.x, avail.y)

    # -- modal rendering ---------------------------------------------------

    _MODAL_OPEN = 1
    _MODAL_CLOSED = 0

    def _render_modal(self, elem: Element) -> None:
        from imgui_bundle import imgui

        md: Any = elem
        eid: str = md.id
        title: str = md.title or md.id
        should_open: bool = md.open
        popup_id = f"{title}##{eid}"
        open_key = f"{eid}__open"
        dismiss_key = f"{eid}__dismissed"

        on = self._MODAL_OPEN
        off = self._MODAL_CLOSED
        was_open = self._widget_state.ensure(open_key, off) == on
        dismissed = self._widget_state.ensure(dismiss_key, off) == on

        # When the agent sets open=False, clear the dismissed latch
        # so the modal can be re-opened later.
        if not should_open:
            if was_open or dismissed:
                self._widget_state.set(open_key, self._MODAL_CLOSED)
                self._widget_state.set(dismiss_key, self._MODAL_CLOSED)
            return

        # Don't re-open if user already dismissed and agent hasn't acked yet.
        if should_open and not was_open and not dismissed:
            imgui.open_popup(popup_id)
            self._widget_state.set(open_key, self._MODAL_OPEN)
            was_open = True

        visible, _p_open = imgui.begin_popup_modal(popup_id, True)  # noqa: FBT003

        if visible:
            for child in md.children:
                self._render_element(child)
            imgui.end_popup()

        if was_open and not visible:
            self._widget_state.set(open_key, self._MODAL_CLOSED)
            self._widget_state.set(dismiss_key, self._MODAL_OPEN)
            self._event_queue.append(
                InteractionMessage(
                    element_id=eid,
                    action="closed",
                    ts=time.time(),
                    value=None,
                )
            )

    # -- draw element rendering --------------------------------------------

    def _render_draw(self, elem: Element) -> None:
        from imgui_bundle import ImVec2, imgui

        draw: Any = elem
        eid: str = draw.id
        width: int = draw.width
        height: int = draw.height
        bg_color: str | None = draw.bg_color
        commands: list[dict[str, Any]] = draw.commands

        canvas_pos = imgui.get_cursor_screen_pos()
        canvas_min = ImVec2(canvas_pos.x, canvas_pos.y)
        canvas_max = ImVec2(canvas_pos.x + width, canvas_pos.y + height)
        draw_list = imgui.get_window_draw_list()

        draw_list.push_clip_rect(canvas_min, canvas_max, True)  # noqa: FBT003

        if bg_color is not None:
            draw_list.add_rect_filled(canvas_min, canvas_max, _to_imgui_color(bg_color))

        ox, oy = canvas_pos.x, canvas_pos.y
        for cmd in commands:
            try:
                self._dispatch_draw_cmd(draw_list, cmd, ox, oy)
            except (KeyError, IndexError, TypeError, ValueError):
                logger.debug("Skipping malformed draw command: %s", cmd)

        draw_list.pop_clip_rect()
        imgui.dummy(ImVec2(width, height))
        _ = eid  # used for future interaction tracking

    def _dispatch_draw_cmd(
        self,
        draw_list: Any,
        cmd: dict[str, Any],
        ox: float,
        oy: float,
    ) -> None:
        from imgui_bundle import ImVec2

        cmd_type = cmd.get("cmd", "")
        color = _to_imgui_color(cmd.get("color", "#FFFFFF"))
        thickness: float = cmd.get("thickness", 1.0)

        if cmd_type == "line":
            p1, p2 = cmd["p1"], cmd["p2"]
            draw_list.add_line(
                ImVec2(ox + p1[0], oy + p1[1]),
                ImVec2(ox + p2[0], oy + p2[1]),
                color,
                thickness,
            )
        elif cmd_type == "rect":
            self._draw_rect(draw_list, cmd, color, thickness, ox, oy)
        elif cmd_type == "circle":
            self._draw_circle(draw_list, cmd, color, thickness, ox, oy)
        elif cmd_type == "triangle":
            self._draw_triangle(draw_list, cmd, color, thickness, ox, oy)
        elif cmd_type == "text":
            pos = cmd.get("pos", [0, 0])
            draw_list.add_text(
                ImVec2(ox + pos[0], oy + pos[1]), color, cmd.get("text", "")
            )
        elif cmd_type == "polyline":
            self._draw_polyline(draw_list, cmd, color, thickness, ox, oy)
        elif cmd_type == "bezier_cubic":
            self._draw_bezier(draw_list, cmd, color, thickness, ox, oy)

    def _draw_rect(
        self,
        dl: Any,
        cmd: dict[str, Any],
        color: int,
        thickness: float,
        ox: float,
        oy: float,
    ) -> None:
        from imgui_bundle import ImVec2

        mn = cmd.get("min", [0, 0])
        mx = cmd.get("max", [0, 0])
        rounding: float = cmd.get("rounding", 0.0)
        if cmd.get("filled", False):
            dl.add_rect_filled(
                ImVec2(ox + mn[0], oy + mn[1]),
                ImVec2(ox + mx[0], oy + mx[1]),
                color,
                rounding,
            )
        else:
            dl.add_rect(
                ImVec2(ox + mn[0], oy + mn[1]),
                ImVec2(ox + mx[0], oy + mx[1]),
                color,
                rounding,
                0,
                thickness,
            )

    def _draw_circle(
        self,
        dl: Any,
        cmd: dict[str, Any],
        color: int,
        thickness: float,
        ox: float,
        oy: float,
    ) -> None:
        from imgui_bundle import ImVec2

        center = cmd.get("center", [0, 0])
        radius: float = cmd.get("radius", 10)
        if cmd.get("filled", False):
            dl.add_circle_filled(ImVec2(ox + center[0], oy + center[1]), radius, color)
        else:
            dl.add_circle(
                ImVec2(ox + center[0], oy + center[1]),
                radius,
                color,
                0,
                thickness,
            )

    def _draw_triangle(
        self,
        dl: Any,
        cmd: dict[str, Any],
        color: int,
        thickness: float,
        ox: float,
        oy: float,
    ) -> None:
        from imgui_bundle import ImVec2

        p1 = cmd["p1"]
        p2 = cmd["p2"]
        p3 = cmd["p3"]
        if cmd.get("filled", False):
            dl.add_triangle_filled(
                ImVec2(ox + p1[0], oy + p1[1]),
                ImVec2(ox + p2[0], oy + p2[1]),
                ImVec2(ox + p3[0], oy + p3[1]),
                color,
            )
        else:
            dl.add_triangle(
                ImVec2(ox + p1[0], oy + p1[1]),
                ImVec2(ox + p2[0], oy + p2[1]),
                ImVec2(ox + p3[0], oy + p3[1]),
                color,
                thickness,
            )

    def _draw_polyline(
        self,
        dl: Any,
        cmd: dict[str, Any],
        color: int,
        thickness: float,
        ox: float,
        oy: float,
    ) -> None:
        from imgui_bundle import ImVec2

        im_draw_flags_closed = 1
        points_raw: list[list[float]] = cmd.get("points", [])
        closed: bool = cmd.get("closed", False)
        points = [ImVec2(ox + p[0], oy + p[1]) for p in points_raw]
        if len(points) >= 2:
            flags = im_draw_flags_closed if closed else 0
            dl.add_polyline(points, color, flags, thickness)

    def _draw_bezier(
        self,
        dl: Any,
        cmd: dict[str, Any],
        color: int,
        thickness: float,
        ox: float,
        oy: float,
    ) -> None:
        from imgui_bundle import ImVec2

        p1, p2, p3, p4 = cmd["p1"], cmd["p2"], cmd["p3"], cmd["p4"]
        dl.add_bezier_cubic(
            ImVec2(ox + p1[0], oy + p1[1]),
            ImVec2(ox + p2[0], oy + p2[1]),
            ImVec2(ox + p3[0], oy + p3[1]),
            ImVec2(ox + p4[0], oy + p4[1]),
            color,
            thickness,
        )

    # -- event flushing ----------------------------------------------------

    def _flush_events(self) -> None:
        if not self._event_queue:
            return
        if self._clients:
            for event in self._event_queue:
                is_world_menu = (
                    event.action == "menu"
                    and isinstance(event.value, dict)
                    and event.value.get("menu") == "World"
                )
                owner_fd = (
                    self._menu_owners.get(event.element_id) if is_world_menu else None
                )
                if owner_fd is not None:
                    target = self._fd_to_client.get(owner_fd)
                    if target is not None:
                        self._send_to_client(target, event)
                else:
                    for client in list(self._clients):
                        self._send_to_client(client, event)
        self._event_queue.clear()
