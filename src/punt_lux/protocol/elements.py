"""Element dataclasses and serialization for the Lux display protocol."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import InitVar, dataclass, field, replace
from typing import Any, Literal, cast

__all__ = [
    "ButtonElement",
    "CheckboxElement",
    "CollapsingHeaderElement",
    "ColorPickerElement",
    "ComboElement",
    "DrawElement",
    "Element",
    "GroupElement",
    "ImageElement",
    "InputNumberElement",
    "InputTextElement",
    "MarkdownElement",
    "ModalElement",
    "Patch",
    "PlotElement",
    "ProgressElement",
    "RadioElement",
    "SelectableElement",
    "SeparatorElement",
    "SliderElement",
    "SpinnerElement",
    "TabBarElement",
    "TableDetail",
    "TableElement",
    "TableFilter",
    "TextElement",
    "TreeElement",
    "WindowElement",
    "_element_to_dict",
    "_patch_from_dict",
    "_patch_to_dict",
    "_strip_none",
    "element_from_dict",
    "element_to_dict",
]

# ---------------------------------------------------------------------------
# Element types (inside Scene messages)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ImageElement:
    """An image to display."""

    id: str
    kind: Literal["image"] = "image"
    path: str | None = None
    data: str | None = None  # base64-encoded
    format: str | None = None  # "png", "jpeg", "svg"
    alt: str | None = None
    width: int | None = None
    height: int | None = None
    tooltip: str | None = None

    def __post_init__(self) -> None:
        if self.path is None and self.data is None:
            msg = "ImageElement requires either 'path' or 'data'"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class TextElement:
    """A text block."""

    id: str
    content: str
    kind: Literal["text"] = "text"
    style: str | None = None  # "body", "heading", "caption", "code"
    tooltip: str | None = None
    color: str | None = None  # hex color e.g. "#FF3333"


@dataclass(frozen=True, slots=True)
class ButtonElement:
    """A clickable button.

    Variants:
      - ``small=True``: compact button (ImGui SmallButton)
      - ``arrow``: directional arrow button ("left"/"right"/"up"/"down")
    """

    id: str
    label: str
    kind: Literal["button"] = "button"
    action: str | None = None
    disabled: bool = False
    small: bool = False
    arrow: str | None = None  # "left", "right", "up", "down"
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class SeparatorElement:
    """A visual divider."""

    kind: Literal["separator"] = "separator"
    id: str | None = None
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class SliderElement:
    """A numeric slider."""

    id: str
    label: str
    kind: Literal["slider"] = "slider"
    value: float = 0.0
    min: float = 0.0
    max: float = 100.0
    format: str = "%.1f"
    integer: bool = False
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class CheckboxElement:
    """A boolean checkbox."""

    id: str
    label: str
    kind: Literal["checkbox"] = "checkbox"
    value: bool = False
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class ComboElement:
    """A dropdown combo box."""

    id: str
    label: str
    kind: Literal["combo"] = "combo"
    items: list[str] = field(default_factory=lambda: list[str]())
    selected: int = 0
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class InputTextElement:
    """A single-line text input."""

    id: str
    label: str
    kind: Literal["input_text"] = "input_text"
    value: str = ""
    hint: str = ""
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class RadioElement:
    """A set of radio buttons."""

    id: str
    label: str
    kind: Literal["radio"] = "radio"
    items: list[str] = field(default_factory=lambda: list[str]())
    selected: int = 0
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class InputNumberElement:
    """A numeric input field with optional step buttons and clamping."""

    id: str
    label: str
    kind: Literal["input_number"] = "input_number"
    value: float = 0.0
    min: float | None = None
    max: float | None = None
    step: float | None = None
    format: str = "%.3f"
    integer: bool = False
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class ColorPickerElement:
    """A color picker with optional alpha channel and full picker mode.

    Modes:
      - default: inline ``ColorEdit3`` (RGB)
      - ``alpha=True``: ``ColorEdit4`` (RGBA), value uses ``#RRGGBBAA``
      - ``picker=True``: full ``ColorPicker3``/``ColorPicker4`` widget
    """

    id: str
    label: str
    kind: Literal["color_picker"] = "color_picker"
    value: str = "#FFFFFF"
    alpha: bool = False
    picker: bool = False
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class DrawElement:
    """A 2D canvas with draw commands (line, rect, circle, etc.)."""

    id: str
    kind: Literal["draw"] = "draw"
    width: int = 400
    height: int = 300
    bg_color: str | None = None
    commands: list[dict[str, Any]] = field(
        default_factory=lambda: list[dict[str, Any]]()
    )
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class GroupElement:
    """A layout container that arranges children in rows or columns.

    Layout modes:
      - ``rows`` (default): vertical stack
      - ``columns``: horizontal side-by-side
      - ``paged``: combo-driven page switcher.  ``children`` are always
        visible (header/nav), ``pages`` are indexed content panels
        switched by the combo identified by ``page_source``.
    """

    id: str
    kind: Literal["group"] = "group"
    layout: str = "rows"  # "rows" | "columns" | "paged"
    children: list[Any] = field(default_factory=lambda: list[Any]())
    pages: list[list[Any]] = field(default_factory=lambda: list[list[Any]]())
    page_source: str | None = None  # id of ComboElement driving page index
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class TabBarElement:
    """A tabbed container. Each tab has a label and child elements."""

    id: str
    kind: Literal["tab_bar"] = "tab_bar"
    tabs: list[dict[str, Any]] = field(default_factory=lambda: list[dict[str, Any]]())
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class CollapsingHeaderElement:
    """A collapsible section with a label and child elements."""

    id: str
    kind: Literal["collapsing_header"] = "collapsing_header"
    label: str = ""
    default_open: bool = False
    children: list[Any] = field(default_factory=lambda: list[Any]())
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class WindowElement:
    """A movable, resizable sub-window inside the display."""

    id: str
    kind: Literal["window"] = "window"
    title: str = ""
    x: float = 50.0
    y: float = 50.0
    width: float = 300.0
    height: float = 200.0
    no_move: bool = False
    no_resize: bool = False
    no_collapse: bool = False
    no_title_bar: bool = False
    no_scrollbar: bool = False
    auto_resize: bool = False
    children: list[Any] = field(default_factory=lambda: list[Any]())
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class SelectableElement:
    """A toggleable list item."""

    id: str
    label: str
    kind: Literal["selectable"] = "selectable"
    selected: bool = False
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class TreeElement:
    """A collapsible tree with recursive nodes.

    Each node in ``nodes`` is a dict with ``"label"`` (str) and optional
    ``"children"`` (list of nodes).  Leaf nodes omit ``"children"`` or
    use an empty list.

    When ``flat`` is True, children render without indentation: branch
    nodes use ``NoTreePushOnOpen`` (arrow toggles but no indent push),
    and leaf nodes render as selectable items instead of tree leaves.
    Useful for inline disclosure patterns where horizontal space is tight.
    """

    id: str
    kind: Literal["tree"] = "tree"
    label: str = ""
    nodes: list[dict[str, Any]] = field(default_factory=lambda: list[dict[str, Any]]())
    flat: bool = False
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class TableFilter:
    """A built-in filter control rendered above a table.

    - ``search``: case-insensitive substring match on specified column(s).
    - ``combo``: exact match dropdown; first item is treated as "All" (no filter).
    """

    type: Literal["search", "combo"]
    column_spec: InitVar[int | list[int]]
    hint: str = ""  # placeholder text (search only)
    items: list[str] | None = None  # dropdown items (combo only)
    label: str = ""  # optional label for the control
    _column: list[int] = field(init=False)

    def __post_init__(self, column_spec: int | list[int]) -> None:
        col = [column_spec] if isinstance(column_spec, int) else list(column_spec)
        object.__setattr__(self, "_column", col)
        if not self._column:
            msg = "TableFilter requires non-empty 'column'"
            raise ValueError(msg)
        if self.type == "combo" and not self.items:
            msg = "TableFilter type='combo' requires non-empty 'items'"
            raise ValueError(msg)

    @property
    def column(self) -> list[int]:
        """Column index(es) this filter operates on (read-only)."""
        return self._column


@dataclass(frozen=True, slots=True)
class TableDetail:
    """Detail data for a built-in list/detail view.

    Each array is parallel to the parent ``TableElement.rows``:
    ``rows[i]`` provides the detail metadata and ``body[i]`` provides
    the long-form text for the *i*-th list row.

    ``fields`` names the metadata columns.  The display renders them
    as a 2-column grid (Field | Value | Field | Value).
    """

    fields: list[str]
    rows: list[list[Any]]
    body: list[str]

    def __post_init__(self) -> None:
        if len(self.rows) != len(self.body):
            msg = (
                "TableDetail rows/body length mismatch: "
                f"{len(self.rows)} vs {len(self.body)}"
            )
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class TableElement:
    """A data table with columns and rows."""

    id: str
    kind: Literal["table"] = "table"
    columns: list[str] = field(default_factory=lambda: list[str]())
    rows: list[list[Any]] = field(default_factory=lambda: list[list[Any]]())
    flags: list[str] = field(default_factory=lambda: ["borders", "row_bg"])
    column_widths: list[float] | None = None
    filters: list[TableFilter] | None = None
    detail: TableDetail | None = None
    tooltip: str | None = None

    def __post_init__(self) -> None:
        cw = self.column_widths
        if cw is not None and len(cw) != len(self.columns):
            msg = (
                f"column_widths length ({len(cw)}) "
                f"must match columns ({len(self.columns)})"
            )
            raise ValueError(msg)
        d = self.detail
        if d is not None and len(d.rows) != len(self.rows):
            msg = (
                f"detail.rows length ({len(d.rows)}) must match rows ({len(self.rows)})"
            )
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class PlotElement:
    """A 2D plot with one or more data series (line, scatter, bar)."""

    id: str
    kind: Literal["plot"] = "plot"
    title: str = ""
    x_label: str = ""
    y_label: str = ""
    width: float = -1  # -1 = auto-fill available width
    height: float = 300
    series: list[dict[str, Any]] = field(default_factory=lambda: list[dict[str, Any]]())
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class ProgressElement:
    """A progress bar."""

    id: str
    kind: Literal["progress"] = "progress"
    fraction: float = 0.0
    label: str = ""
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class SpinnerElement:
    """An animated loading spinner."""

    id: str
    kind: Literal["spinner"] = "spinner"
    label: str = ""
    radius: float = 16.0
    color: str = "#3399FF"
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class MarkdownElement:
    """A block of rendered markdown text."""

    id: str
    content: str
    kind: Literal["markdown"] = "markdown"
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class ModalElement:
    """A modal popup dialog that blocks interaction with background content.

    Set ``open=True`` to show the modal.  Children render inside.
    The display emits a ``"closed"`` event when the user dismisses it
    (Escape or X button).  Button clicks inside fire normal button events.
    """

    id: str
    kind: Literal["modal"] = "modal"
    title: str = ""
    open: bool = True
    children: list[Any] = field(default_factory=lambda: list[Any]())
    tooltip: str | None = None


Element = (
    ImageElement
    | TextElement
    | ButtonElement
    | SeparatorElement
    | SliderElement
    | CheckboxElement
    | ComboElement
    | InputTextElement
    | InputNumberElement
    | RadioElement
    | ColorPickerElement
    | DrawElement
    | GroupElement
    | TabBarElement
    | CollapsingHeaderElement
    | WindowElement
    | SelectableElement
    | TreeElement
    | TableElement
    | PlotElement
    | ProgressElement
    | SpinnerElement
    | MarkdownElement
    | ModalElement
)

# ---------------------------------------------------------------------------
# Patch
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Patch:
    """A single element patch within an UpdateMessage."""

    id: str
    set: dict[str, Any] | None = None
    remove: bool = False


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def _strip_none(d: dict[str, Any]) -> dict[str, Any]:
    """Remove keys whose value is None."""
    return {k: v for k, v in d.items() if v is not None}


def _image_to_dict(elem: ImageElement) -> dict[str, Any]:
    return _strip_none(
        {
            "kind": elem.kind,
            "id": elem.id,
            "path": elem.path,
            "data": elem.data,
            "format": elem.format,
            "alt": elem.alt,
            "width": elem.width,
            "height": elem.height,
        }
    )


def _text_to_dict(elem: TextElement) -> dict[str, Any]:
    return _strip_none(
        {
            "kind": elem.kind,
            "id": elem.id,
            "content": elem.content,
            "style": elem.style,
            "color": elem.color,
        }
    )


def _button_to_dict(elem: ButtonElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
        "action": elem.action,
    }
    if elem.disabled:
        d["disabled"] = True
    if elem.small:
        d["small"] = True
    if elem.arrow is not None:
        d["arrow"] = elem.arrow
    return _strip_none(d)


def _separator_to_dict(elem: SeparatorElement) -> dict[str, Any]:
    d: dict[str, Any] = {"kind": elem.kind}
    if elem.id is not None:
        d["id"] = elem.id
    return d


def _slider_to_dict(elem: SliderElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
        "value": elem.value,
        "min": elem.min,
        "max": elem.max,
        "format": elem.format,
    }
    if elem.integer:
        d["integer"] = True
    return d


def _checkbox_to_dict(elem: CheckboxElement) -> dict[str, Any]:
    return {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
        "value": elem.value,
    }


def _combo_to_dict(elem: ComboElement) -> dict[str, Any]:
    return {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
        "items": elem.items,
        "selected": elem.selected,
    }


def _input_text_to_dict(elem: InputTextElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
        "value": elem.value,
    }
    if elem.hint:
        d["hint"] = elem.hint
    return d


def _radio_to_dict(elem: RadioElement) -> dict[str, Any]:
    return {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
        "items": elem.items,
        "selected": elem.selected,
    }


def _input_number_to_dict(elem: InputNumberElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
        "value": elem.value,
        "format": elem.format,
    }
    if elem.min is not None:
        d["min"] = elem.min
    if elem.max is not None:
        d["max"] = elem.max
    if elem.step is not None:
        d["step"] = elem.step
    if elem.integer:
        d["integer"] = True
    return d


def _color_picker_to_dict(elem: ColorPickerElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
        "value": elem.value,
    }
    if elem.alpha:
        d["alpha"] = True
    if elem.picker:
        d["picker"] = True
    return d


def _draw_to_dict(elem: DrawElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "width": elem.width,
        "height": elem.height,
        "commands": elem.commands,
    }
    if elem.bg_color is not None:
        d["bg_color"] = elem.bg_color
    return d


def _group_to_dict(elem: GroupElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "layout": elem.layout,
        "children": [_element_to_dict(c) for c in elem.children],
    }
    if elem.pages:
        d["pages"] = [[_element_to_dict(e) for e in page] for page in elem.pages]
    if elem.page_source is not None:
        d["page_source"] = elem.page_source
    return d


def _tab_bar_to_dict(elem: TabBarElement) -> dict[str, Any]:
    return {
        "kind": elem.kind,
        "id": elem.id,
        "tabs": [
            {
                "label": t.get("label", "Tab"),
                "children": [_element_to_dict(c) for c in t.get("children", [])],
            }
            for t in elem.tabs
        ],
    }


def _collapsing_header_to_dict(elem: CollapsingHeaderElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
        "children": [_element_to_dict(c) for c in elem.children],
    }
    if elem.default_open:
        d["default_open"] = True
    return d


def _window_elem_to_dict(elem: WindowElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "title": elem.title,
        "x": elem.x,
        "y": elem.y,
        "width": elem.width,
        "height": elem.height,
        "children": [_element_to_dict(c) for c in elem.children],
    }
    if elem.no_move:
        d["no_move"] = True
    if elem.no_resize:
        d["no_resize"] = True
    if elem.no_collapse:
        d["no_collapse"] = True
    if elem.no_title_bar:
        d["no_title_bar"] = True
    if elem.no_scrollbar:
        d["no_scrollbar"] = True
    if elem.auto_resize:
        d["auto_resize"] = True
    return d


def _selectable_to_dict(elem: SelectableElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
    }
    if elem.selected:
        d["selected"] = True
    return d


def _tree_to_dict(elem: TreeElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
        "nodes": elem.nodes,
    }
    if elem.flat:
        d["flat"] = True
    return d


def _table_detail_to_dict(d: TableDetail) -> dict[str, Any]:
    return {"fields": d.fields, "rows": d.rows, "body": d.body}


def _table_detail_from_dict(d: dict[str, Any]) -> TableDetail:
    return TableDetail(
        fields=d.get("fields", []),
        rows=d.get("rows", []),
        body=d.get("body", []),
    )


def _table_filter_to_dict(f: TableFilter) -> dict[str, Any]:
    d: dict[str, Any] = {"type": f.type, "column": f.column}
    if f.hint:
        d["hint"] = f.hint
    if f.items is not None:
        d["items"] = f.items
    if f.label:
        d["label"] = f.label
    return d


def _table_filter_from_dict(d: dict[str, Any]) -> TableFilter:
    ftype = d["type"]
    if ftype not in ("search", "combo"):
        msg = f"Unknown table filter type: {ftype!r}"
        raise ValueError(msg)
    return TableFilter(
        type=ftype,
        column_spec=d["column"],
        hint=d.get("hint", ""),
        items=d.get("items"),
        label=d.get("label", ""),
    )


def _table_to_dict(elem: TableElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "columns": elem.columns,
        "rows": elem.rows,
        "flags": elem.flags,
    }
    if elem.column_widths is not None:
        d["column_widths"] = elem.column_widths
    if elem.filters is not None:
        d["filters"] = [_table_filter_to_dict(f) for f in elem.filters]
    if elem.detail is not None:
        d["detail"] = _table_detail_to_dict(elem.detail)
    return d


def _plot_to_dict(elem: PlotElement) -> dict[str, Any]:
    return {
        "kind": elem.kind,
        "id": elem.id,
        "title": elem.title,
        "x_label": elem.x_label,
        "y_label": elem.y_label,
        "width": elem.width,
        "height": elem.height,
        "series": elem.series,
    }


def _progress_to_dict(elem: ProgressElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "fraction": elem.fraction,
    }
    if elem.label:
        d["label"] = elem.label
    return d


def _spinner_to_dict(elem: SpinnerElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "radius": elem.radius,
        "color": elem.color,
    }
    if elem.label:
        d["label"] = elem.label
    return d


def _markdown_to_dict(elem: MarkdownElement) -> dict[str, Any]:
    return {
        "kind": elem.kind,
        "id": elem.id,
        "content": elem.content,
    }


def _modal_to_dict(elem: ModalElement) -> dict[str, Any]:
    return {
        "kind": elem.kind,
        "id": elem.id,
        "title": elem.title,
        "open": elem.open,
        "children": [_element_to_dict(c) for c in elem.children],
    }


_ELEMENT_SERIALIZERS: dict[type, Callable[..., dict[str, Any]]] = {
    ImageElement: _image_to_dict,
    TextElement: _text_to_dict,
    ButtonElement: _button_to_dict,
    SeparatorElement: _separator_to_dict,
    SliderElement: _slider_to_dict,
    CheckboxElement: _checkbox_to_dict,
    ComboElement: _combo_to_dict,
    InputTextElement: _input_text_to_dict,
    InputNumberElement: _input_number_to_dict,
    RadioElement: _radio_to_dict,
    ColorPickerElement: _color_picker_to_dict,
    DrawElement: _draw_to_dict,
    GroupElement: _group_to_dict,
    TabBarElement: _tab_bar_to_dict,
    CollapsingHeaderElement: _collapsing_header_to_dict,
    WindowElement: _window_elem_to_dict,
    SelectableElement: _selectable_to_dict,
    TreeElement: _tree_to_dict,
    TableElement: _table_to_dict,
    PlotElement: _plot_to_dict,
    ProgressElement: _progress_to_dict,
    SpinnerElement: _spinner_to_dict,
    MarkdownElement: _markdown_to_dict,
    ModalElement: _modal_to_dict,
}


def _element_to_dict(elem: Element) -> dict[str, Any]:
    """Serialize an Element dataclass to a JSON-compatible dict."""
    serializer = _ELEMENT_SERIALIZERS.get(type(elem))
    if serializer is not None:
        result: dict[str, Any] = serializer(elem)
        tooltip = getattr(elem, "tooltip", None)
        if tooltip is not None:
            result["tooltip"] = tooltip
        return result
    msg = f"Unknown element type: {type(elem)}"
    raise TypeError(msg)


def element_to_dict(elem: Element) -> dict[str, Any]:
    """Serialize an Element dataclass to a JSON-compatible dict."""
    return _element_to_dict(elem)


def _image_from_dict(d: dict[str, Any]) -> ImageElement:
    return ImageElement(
        id=d["id"],
        path=d.get("path"),
        data=d.get("data"),
        format=d.get("format"),
        alt=d.get("alt"),
        width=d.get("width"),
        height=d.get("height"),
    )


def _text_from_dict(d: dict[str, Any]) -> TextElement:
    return TextElement(
        id=d["id"],
        content=d.get("content", ""),
        style=d.get("style"),
        color=d.get("color"),
    )


def _button_from_dict(d: dict[str, Any]) -> ButtonElement:
    return ButtonElement(
        id=d["id"],
        label=d.get("label", ""),
        action=d.get("action"),
        disabled=d.get("disabled", False),
        small=d.get("small", False),
        arrow=d.get("arrow"),
    )


def _separator_from_dict(d: dict[str, Any]) -> SeparatorElement:
    return SeparatorElement(id=d.get("id"))


def _slider_from_dict(d: dict[str, Any]) -> SliderElement:
    return SliderElement(
        id=d["id"],
        label=d.get("label", ""),
        value=d.get("value", 0.0),
        min=d.get("min", 0.0),
        max=d.get("max", 100.0),
        format=d.get("format", "%.1f"),
        integer=d.get("integer", False),
    )


def _checkbox_from_dict(d: dict[str, Any]) -> CheckboxElement:
    return CheckboxElement(
        id=d["id"],
        label=d.get("label", ""),
        value=d.get("value", False),
    )


def _combo_from_dict(d: dict[str, Any]) -> ComboElement:
    return ComboElement(
        id=d["id"],
        label=d.get("label", ""),
        items=d.get("items", []),
        selected=d.get("selected", 0),
    )


def _input_text_from_dict(d: dict[str, Any]) -> InputTextElement:
    return InputTextElement(
        id=d["id"],
        label=d.get("label", ""),
        value=d.get("value", ""),
        hint=d.get("hint", ""),
    )


def _radio_from_dict(d: dict[str, Any]) -> RadioElement:
    return RadioElement(
        id=d["id"],
        label=d.get("label", ""),
        items=d.get("items", []),
        selected=d.get("selected", 0),
    )


def _input_number_from_dict(d: dict[str, Any]) -> InputNumberElement:
    return InputNumberElement(
        id=d["id"],
        label=d.get("label", ""),
        value=d.get("value", 0.0),
        min=d.get("min"),
        max=d.get("max"),
        step=d.get("step"),
        format=d.get("format", "%.3f"),
        integer=d.get("integer", False),
    )


def _color_picker_from_dict(d: dict[str, Any]) -> ColorPickerElement:
    return ColorPickerElement(
        id=d["id"],
        label=d.get("label", ""),
        value=d.get("value", "#FFFFFF"),
        alpha=d.get("alpha", False),
        picker=d.get("picker", False),
    )


def _draw_from_dict(d: dict[str, Any]) -> DrawElement:
    return DrawElement(
        id=d["id"],
        width=d.get("width", 400),
        height=d.get("height", 300),
        bg_color=d.get("bg_color"),
        commands=d.get("commands", []),
    )


def _group_from_dict(d: dict[str, Any]) -> GroupElement:
    pages_raw = d.get("pages", [])
    pages = [[element_from_dict(e) for e in page] for page in pages_raw]
    return GroupElement(
        id=d["id"],
        layout=d.get("layout", "rows"),
        children=[element_from_dict(c) for c in d.get("children", [])],
        pages=pages,
        page_source=d.get("page_source"),
    )


def _tab_bar_from_dict(d: dict[str, Any]) -> TabBarElement:
    tabs: list[dict[str, Any]] = [
        {
            "label": t.get("label", "Tab"),
            "children": [element_from_dict(c) for c in t.get("children", [])],
        }
        for t in d.get("tabs", [])
    ]
    return TabBarElement(id=d["id"], tabs=tabs)


def _collapsing_header_from_dict(d: dict[str, Any]) -> CollapsingHeaderElement:
    return CollapsingHeaderElement(
        id=d["id"],
        label=d.get("label", ""),
        default_open=d.get("default_open", False),
        children=[element_from_dict(c) for c in d.get("children", [])],
    )


def _window_from_dict(d: dict[str, Any]) -> WindowElement:
    return WindowElement(
        id=d["id"],
        title=d.get("title", ""),
        x=d.get("x", 50.0),
        y=d.get("y", 50.0),
        width=d.get("width", 300.0),
        height=d.get("height", 200.0),
        no_move=d.get("no_move", False),
        no_resize=d.get("no_resize", False),
        no_collapse=d.get("no_collapse", False),
        no_title_bar=d.get("no_title_bar", False),
        no_scrollbar=d.get("no_scrollbar", False),
        auto_resize=d.get("auto_resize", False),
        children=[element_from_dict(c) for c in d.get("children", [])],
    )


def _selectable_from_dict(d: dict[str, Any]) -> SelectableElement:
    return SelectableElement(
        id=d["id"],
        label=d.get("label", ""),
        selected=d.get("selected", False),
    )


def _normalize_tree_nodes(raw: Any) -> list[dict[str, Any]]:
    """Coerce tree nodes to a valid list of node dicts, non-mutating."""
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    for item in cast("list[Any]", raw):  # type: ignore[redundant-cast]
        if not isinstance(item, dict):
            continue
        src = cast("dict[str, Any]", item)
        node: dict[str, Any] = {k: v for k, v in src.items() if k != "children"}
        raw_children = src.get("children")
        if raw_children is not None:
            node["children"] = _normalize_tree_nodes(raw_children)
        result.append(node)
    return result


def _tree_from_dict(d: dict[str, Any]) -> TreeElement:
    return TreeElement(
        id=d["id"],
        label=d.get("label", ""),
        nodes=_normalize_tree_nodes(d.get("nodes", [])),
        flat=d.get("flat", False),
    )


def _table_from_dict(d: dict[str, Any]) -> TableElement:
    raw_filters = d.get("filters")
    raw_detail = d.get("detail")
    return TableElement(
        id=d["id"],
        columns=d.get("columns", []),
        rows=d.get("rows", []),
        flags=d.get("flags", ["borders", "row_bg"]),
        column_widths=d.get("column_widths"),
        filters=[_table_filter_from_dict(f) for f in raw_filters]
        if raw_filters is not None
        else None,
        detail=_table_detail_from_dict(raw_detail) if raw_detail is not None else None,
    )


def _plot_from_dict(d: dict[str, Any]) -> PlotElement:
    return PlotElement(
        id=d["id"],
        title=d.get("title", ""),
        x_label=d.get("x_label", ""),
        y_label=d.get("y_label", ""),
        width=d.get("width", -1),
        height=d.get("height", 300),
        series=d.get("series", []),
    )


def _progress_from_dict(d: dict[str, Any]) -> ProgressElement:
    return ProgressElement(
        id=d["id"],
        fraction=d.get("fraction", 0.0),
        label=d.get("label", ""),
    )


def _spinner_from_dict(d: dict[str, Any]) -> SpinnerElement:
    return SpinnerElement(
        id=d["id"],
        label=d.get("label", ""),
        radius=d.get("radius", 16.0),
        color=d.get("color", "#3399FF"),
    )


def _markdown_from_dict(d: dict[str, Any]) -> MarkdownElement:
    return MarkdownElement(
        id=d["id"],
        content=d.get("content", ""),
    )


def _modal_from_dict(d: dict[str, Any]) -> ModalElement:
    return ModalElement(
        id=d["id"],
        title=d.get("title", ""),
        open=d.get("open", True),
        children=[element_from_dict(c) for c in d.get("children", [])],
    )


_ELEMENT_DESERIALIZERS: dict[str, Callable[[dict[str, Any]], Element]] = {
    "image": _image_from_dict,
    "text": _text_from_dict,
    "button": _button_from_dict,
    "separator": _separator_from_dict,
    "slider": _slider_from_dict,
    "checkbox": _checkbox_from_dict,
    "combo": _combo_from_dict,
    "input_text": _input_text_from_dict,
    "input_number": _input_number_from_dict,
    "radio": _radio_from_dict,
    "color_picker": _color_picker_from_dict,
    "draw": _draw_from_dict,
    "group": _group_from_dict,
    "tab_bar": _tab_bar_from_dict,
    "collapsing_header": _collapsing_header_from_dict,
    "window": _window_from_dict,
    "selectable": _selectable_from_dict,
    "tree": _tree_from_dict,
    "table": _table_from_dict,
    "plot": _plot_from_dict,
    "progress": _progress_from_dict,
    "spinner": _spinner_from_dict,
    "markdown": _markdown_from_dict,
    "modal": _modal_from_dict,
}


def element_from_dict(d: dict[str, Any]) -> Element:
    """Deserialize a dict to the appropriate Element dataclass.

    Accepts dicts matching this module's element schema or as supplied by
    MCP tool callers.  Missing ``content``/``label`` keys default to ``""``.
    """
    kind = d.get("kind", "text")
    deserializer = _ELEMENT_DESERIALIZERS.get(kind)
    if deserializer is not None:
        elem = deserializer(d)
        tooltip = d.get("tooltip")
        if tooltip is not None:
            elem = replace(elem, tooltip=tooltip)
        return elem
    msg = f"Unknown element kind: {kind!r}"
    raise ValueError(msg)


def _patch_to_dict(p: Patch) -> dict[str, Any]:
    d: dict[str, Any] = {"id": p.id}
    if p.set is not None:
        d["set"] = p.set
    if p.remove:
        d["remove"] = True
    return d


def _patch_from_dict(d: dict[str, Any]) -> Patch:
    return Patch(
        id=d["id"],
        set=d.get("set"),
        remove=d.get("remove", False),
    )
