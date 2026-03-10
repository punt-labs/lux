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
from typing import TYPE_CHECKING, Any, ClassVar, cast

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
    FrameReader,
    GroupElement,
    InputTextElement,
    InteractionMessage,
    MenuMessage,
    PingMessage,
    PongMessage,
    RadioElement,
    ReadyMessage,
    SceneMessage,
    SelectableElement,
    SliderElement,
    TabBarElement,
    ThemeMessage,
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


def _parse_hex_color(hex_str: str) -> tuple[int, int, int, int]:
    """Parse a hex color string to (r, g, b, a) ints 0-255."""
    h = hex_str.lstrip("#")
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
        logger.warning("Invalid hex color %r; using fallback white", hex_str)
    return (255, 255, 255, 255)


def _color_to_hex(r: float, g: float, b: float) -> str:
    """Convert float RGB (0-1) to hex string."""
    ri = int(max(0.0, min(1.0, r)) * 255)
    gi = int(max(0.0, min(1.0, g)) * 255)
    bi = int(max(0.0, min(1.0, b)) * 255)
    return f"#{ri:02X}{gi:02X}{bi:02X}"


def _hex_to_imgui_color(hex_str: str) -> int:
    """Convert hex string to ImGui packed color (ImU32)."""
    from imgui_bundle import ImVec4, imgui

    r, g, b, a = _parse_hex_color(hex_str)
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
        r, g, b, _a = _parse_hex_color(elem.value)
        from imgui_bundle import ImVec4

        return ImVec4(r / 255.0, g / 255.0, b / 255.0, 1.0)
    return None


# ---------------------------------------------------------------------------
# Recursive element tree helpers
# ---------------------------------------------------------------------------


def _get_children(elem: Element) -> list[list[Any]]:
    """Return all child lists owned by a container element."""
    if isinstance(elem, (GroupElement, CollapsingHeaderElement, WindowElement)):
        return [elem.children]
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


def _render_table_rows(
    indexed_rows: list[IndexedRow],
    num_cols: int,
    *,
    selectable: bool,
    table_id: str,
    widget_state: WidgetState,
    sel_key: str,
    imgui: Any,
) -> int:
    """Render table body rows, with optional row selection for detail views.

    Returns the currently selected original row index (-1 if none).
    """
    selected_orig: int = widget_state.ensure(sel_key, -1)
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
            else:
                imgui.text_wrapped(str(cell))
    return selected_orig


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
    return [max(w, 1.0) for w in weights]


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
        self._scenes: dict[str, SceneMessage] = {}  # ordered by insertion
        self._scene_order: list[str] = []  # explicit tab order
        self._active_tab: str | None = None  # currently selected tab
        self._scene_widget_state: dict[str, WidgetState] = {}  # per-scene
        self._scene_render_fn_state: dict[str, dict[str, _RenderFnState]] = {}
        self._event_queue: list[InteractionMessage] = []
        self._textures = TextureCache()
        self._widget_state = WidgetState()  # active scene's state (swapped)
        self._dirty_windows: set[str] = set()
        self._agent_menus: list[dict[str, Any]] = []
        self._render_fn_state: dict[str, _RenderFnState] = {}  # active (swapped)
        self._themes: list[Any] = []
        self._decorated: bool = True
        self._opacity: float = 1.0
        self._font_scale: float = 1.1
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
        hello_imgui.load_font(primary, 15.0, params)
        logger.info("Loaded primary font: %s", primary)

        for sym_path in merge_fonts:
            merge_params = hello_imgui.FontLoadingParams()
            merge_params.inside_assets = False
            merge_params.merge_to_last_font = True
            hello_imgui.load_font(sym_path, 15.0, merge_params)
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
        runner_params.app_window_params.window_geometry.size = (800, 600)
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
        immapp.run(runner_params, addons)

    # -- ImGui callbacks ---------------------------------------------------

    def _on_post_init(self) -> None:
        """Called once the OpenGL context is ready."""
        from imgui_bundle import hello_imgui, imgui_md

        self._themes = list(hello_imgui.ImGuiTheme_)
        imgui_md.initialize_markdown()
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
            self._show_theme_menu(imgui)
            self._show_window_menu(imgui)
            for menu in self._agent_menus:
                self._show_agent_menu(imgui, menu)
        except Exception:
            logger.exception("Error rendering menus")

    def _show_theme_menu(self, imgui: Any) -> None:
        from imgui_bundle import hello_imgui

        if imgui.begin_menu("Theme"):
            try:
                for theme in self._themes:
                    name = theme.name.replace("_", " ").title()
                    if imgui.menu_item(name, "", False)[0]:  # noqa: FBT003
                        hello_imgui.apply_theme(theme)
            finally:
                imgui.end_menu()

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

        if imgui.begin_menu("Window"):
            try:
                params = hello_imgui.get_runner_params()
                wp = params.app_window_params

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

                if imgui.menu_item("Reset Size", "", False)[0]:  # noqa: FBT003
                    hello_imgui.change_window_size((800, 600))

                imgui.separator()

                _, wp.top_most = imgui.menu_item("Always on Top", "", wp.top_most)

                clicked, _ = imgui.menu_item("Borderless", "", not self._decorated)
                if clicked:
                    self._decorated = not self._decorated
                    self._set_glfw_decorated(decorated=self._decorated)

                imgui.separator()

                changed, value = imgui.slider_float("Opacity", self._opacity, 0.2, 1.0)
                if changed:
                    self._opacity = value
                    self._set_glfw_opacity(opacity=value)
            finally:
                imgui.end_menu()

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
        from imgui_bundle import hello_imgui

        if imgui.begin_menu("Lux"):
            try:
                from punt_lux import __version__

                imgui.menu_item(
                    f"Lux v{__version__}",
                    "",
                    False,  # noqa: FBT003
                    False,  # noqa: FBT003
                )
                imgui.separator()
                if imgui.menu_item("Increase Font", "Cmd + +", False)[0]:  # noqa: FBT003
                    self._font_scale = min(round(self._font_scale + 0.1, 1), 3.0)
                if imgui.menu_item("Decrease Font", "Cmd + -", False)[0]:  # noqa: FBT003
                    self._font_scale = max(round(self._font_scale - 0.1, 1), 0.5)
                imgui.separator()
                if imgui.menu_item("Quit", "Cmd + Q", False)[0]:  # noqa: FBT003
                    hello_imgui.get_runner_params().app_shall_exit = True
            finally:
                imgui.end_menu()

    def _show_agent_menu(self, imgui: Any, menu: dict[str, Any]) -> None:
        if imgui.begin_menu(menu.get("label", "Custom")):
            try:
                for item in menu.get("items", []):
                    label = item.get("label")
                    if label is None:
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
                    if clicked and "id" in item:
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
            self._clients.append(conn)
            self._readers[conn.fileno()] = FrameReader()
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
            for msg in reader.drain_typed():
                self._handle_message(sock, msg)
                if sock not in self._clients:
                    return  # removed during handle (e.g. send failed)
        except (ConnectionError, OSError):
            self._remove_client(sock)
        except ValueError:
            logger.warning("Malformed message from fd %d, disconnecting", sock.fileno())
            self._remove_client(sock)

    def _remove_client(self, sock: socket.socket) -> None:
        if sock not in self._clients:
            return  # already removed — make idempotent
        self._clients.remove(sock)
        try:
            fd = sock.fileno()
        except OSError:
            fd = None
        if fd is not None:
            self._readers.pop(fd, None)
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
            self._scene_widget_state.clear()
            self._scene_render_fn_state.clear()
            self._event_queue.clear()
            self._dirty_windows.clear()
            self._widget_state = WidgetState()
            self._render_fn_state = {}
        elif isinstance(msg, MenuMessage):
            self._agent_menus = msg.menus
        elif isinstance(msg, ThemeMessage):
            self._apply_theme(msg.theme)
        elif isinstance(msg, PingMessage):
            self._send_to_client(sock, PongMessage(ts=msg.ts, display_ts=time.time()))

    def _handle_scene(self, sock: socket.socket, msg: SceneMessage) -> None:
        old_scene = self._scenes.get(msg.id)
        is_new = old_scene is None
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
            # Replace-in-place: drain events for elements removed from this scene
            old_ids: set[str] = set()
            for elem in old_scene.elements:  # type: ignore[union-attr]
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
        self._send_to_client(sock, AckMessage(scene_id=msg.id, ts=time.time()))
        if self._test_auto_click:
            self._auto_click_buttons(msg)

    def _apply_update(self, msg: UpdateMessage) -> None:
        scene = self._scenes.get(msg.scene_id)
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

        if not self._scenes:
            self._render_idle(imgui)
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
        """Render an ambient idle screen with radial light rays and flame."""
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
        text = "Ready"
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
            # Drain events and clean up window state for dismissed scene
            dismissed_ids: set[str] = set()
            for elem in dismissed.elements:
                dismissed_ids.update(_collect_ids(elem))
                if isinstance(elem, WindowElement):
                    self._dirty_windows.discard(elem.id)
            self._event_queue = [
                ev for ev in self._event_queue if ev.element_id not in dismissed_ids
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
    }

    def _render_element(self, elem: Element) -> None:
        from imgui_bundle import imgui

        method_name = self._RENDERERS.get(elem.kind)
        if method_name is not None:
            getattr(self, method_name)(elem)
        else:
            imgui.text(f"[unsupported element: {elem.kind}]")

        tooltip = getattr(elem, "tooltip", None)
        if tooltip:
            imgui.set_item_tooltip(tooltip)

    def _render_text(self, elem: Element) -> None:
        from imgui_bundle import ImVec4, imgui

        text_elem: Any = elem
        content: str = text_elem.content
        style: str | None = text_elem.style

        if style == "heading":
            imgui.separator_text(content)
        elif style == "caption":
            imgui.text_colored(ImVec4(0.6, 0.6, 0.6, 1.0), content)
        elif style == "code":
            imgui.indent(10.0)
            imgui.text(content)
            imgui.unindent(10.0)
        else:
            imgui.text_wrapped(content)

    def _render_button(self, elem: Element) -> None:
        from imgui_bundle import imgui

        btn: Any = elem
        label: str = btn.label
        eid: str = btn.id
        action: str = btn.action or eid
        disabled: bool = btn.disabled

        if disabled:
            imgui.begin_disabled()

        if imgui.button(f"{label}##{eid}"):
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

        r, g, b, _a = _parse_hex_color(hex_str)
        initial = ImVec4(r / 255.0, g / 255.0, b / 255.0, 1.0)
        current = self._widget_state.ensure(eid, initial)

        changed, new_color = imgui.color_edit3(f"{label}##{eid}", current)
        if changed:
            self._widget_state.set(eid, new_color)
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
        for i, child in enumerate(grp.children):
            if layout == "columns" and i > 0:
                imgui.same_line()
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

        if label:
            imgui.text(label)
        for i, node in enumerate(nodes):
            self._render_tree_node(node, f"{eid}_{i}", eid)

    def _render_tree_node(
        self, node: dict[str, Any], node_id: str, tree_id: str
    ) -> None:
        from imgui_bundle import imgui

        label: str = node.get("label", "")
        children: list[dict[str, Any]] = node.get("children", [])

        if children:
            opened = imgui.tree_node(f"{label}##{node_id}")
            if imgui.is_item_clicked():
                self._emit_node_click(tree_id, node_id, label)
            if opened:
                for i, child in enumerate(children):
                    self._render_tree_node(child, f"{node_id}_{i}", tree_id)
                imgui.tree_pop()
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

        flag_map = {
            "borders": imgui.TableFlags_.borders.value,
            "row_bg": imgui.TableFlags_.row_bg.value,
            "resizable": imgui.TableFlags_.resizable.value,
            "sortable": imgui.TableFlags_.sortable.value,
        }
        table_flags = 0
        for f in flags_list:
            table_flags |= flag_map.get(f, 0)

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

        if imgui.begin_table(imgui_id, num_cols, table_flags):
            stretch = imgui.TableColumnFlags_.width_stretch.value
            for col_idx, col_name in enumerate(columns):
                imgui.table_setup_column(col_name, stretch, weights[col_idx])
            imgui.table_headers_row()

            selected_orig = _render_table_rows(
                page_rows,
                num_cols,
                selectable=has_detail,
                table_id=eid,
                widget_state=self._widget_state,
                sel_key=sel_key,
                imgui=imgui,
            )
            imgui.end_table()

        else:
            selected_orig = self._widget_state.ensure(sel_key, -1)

        # Keyboard navigation — up/down arrows move selection
        if has_detail:
            selected_orig = _handle_table_keyboard_nav(
                page_rows,
                selected_orig,
                sel_key,
                self._widget_state,
                imgui,
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

            r, g, b, _a = _parse_hex_color(color_hex)
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
            from imgui_bundle import imgui_md

            imgui_md.render_unindented(md.content)
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
            draw_list.add_rect_filled(
                canvas_min, canvas_max, _hex_to_imgui_color(bg_color)
            )

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
        color = _hex_to_imgui_color(cmd.get("color", "#FFFFFF"))
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
                for client in list(self._clients):
                    self._send_to_client(client, event)
        self._event_queue.clear()
