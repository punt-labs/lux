"""Layout container elements — group, tabs, headers, windows, modals, trees."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, cast

__all__ = [
    "CollapsingHeaderElement",
    "GroupElement",
    "ModalElement",
    "TabBarElement",
    "TreeElement",
    "WindowElement",
]


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


# Container codecs recurse via the package-level dispatcher in
# protocol/elements/__init__.py. Importing element_to_dict / element_from_dict
# at module import time would create a circular import — the aggregator
# imports this module to build the union and dispatch tables, so this module
# cannot import the dispatchers eagerly. The aggregator calls
# ``install_dispatchers()`` once at import time to inject the recursion
# functions, after which the codec functions resolve them at call time.
_RecurseToDict = Callable[[Any], dict[str, Any]]
_RecurseFromDict = Callable[[dict[str, Any]], Any]


# Package-level recursion functions, installed by elements/__init__.py
# after the package's top-level dispatchers (element_to_dict / element_from_dict)
# are defined. Container codecs in this module must recurse via these, not
# import directly — that would create a circular package import.
_to_dict_fn: _RecurseToDict | None = None
_from_dict_fn: _RecurseFromDict | None = None


def install_dispatchers(
    to_dict: _RecurseToDict,
    from_dict: _RecurseFromDict,
) -> None:
    """Inject package-level dispatchers used by container codecs."""
    # Install-once module state, set from elements/__init__.py
    global _to_dict_fn, _from_dict_fn
    _to_dict_fn = to_dict
    _from_dict_fn = from_dict


def _to_dict_dispatch() -> _RecurseToDict:
    if _to_dict_fn is None:
        msg = "layout codecs used before dispatchers installed"
        raise RuntimeError(msg)
    return _to_dict_fn


def _from_dict_dispatch() -> _RecurseFromDict:
    if _from_dict_fn is None:
        msg = "layout codecs used before dispatchers installed"
        raise RuntimeError(msg)
    return _from_dict_fn


def _group_to_dict(elem: GroupElement) -> dict[str, Any]:
    recurse = _to_dict_dispatch()
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "layout": elem.layout,
        "children": [recurse(c) for c in elem.children],
    }
    if elem.pages:
        d["pages"] = [[recurse(e) for e in page] for page in elem.pages]
    if elem.page_source is not None:
        d["page_source"] = elem.page_source
    return d


def _tab_bar_to_dict(elem: TabBarElement) -> dict[str, Any]:
    recurse = _to_dict_dispatch()
    return {
        "kind": elem.kind,
        "id": elem.id,
        "tabs": [
            {
                "label": t.get("label", "Tab"),
                "children": [recurse(c) for c in t.get("children", [])],
            }
            for t in elem.tabs
        ],
    }


def _collapsing_header_to_dict(elem: CollapsingHeaderElement) -> dict[str, Any]:
    recurse = _to_dict_dispatch()
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "label": elem.label,
        "children": [recurse(c) for c in elem.children],
    }
    if elem.default_open:
        d["default_open"] = True
    return d


def _window_to_dict(elem: WindowElement) -> dict[str, Any]:
    recurse = _to_dict_dispatch()
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "title": elem.title,
        "x": elem.x,
        "y": elem.y,
        "width": elem.width,
        "height": elem.height,
        "children": [recurse(c) for c in elem.children],
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


def _modal_to_dict(elem: ModalElement) -> dict[str, Any]:
    recurse = _to_dict_dispatch()
    return {
        "kind": elem.kind,
        "id": elem.id,
        "title": elem.title,
        "open": elem.open,
        "children": [recurse(c) for c in elem.children],
    }


def _group_from_dict(d: dict[str, Any]) -> GroupElement:
    recurse = _from_dict_dispatch()
    pages_raw = d.get("pages", [])
    pages = [[recurse(e) for e in page] for page in pages_raw]
    return GroupElement(
        id=d["id"],
        layout=d.get("layout", "rows"),
        children=[recurse(c) for c in d.get("children", [])],
        pages=pages,
        page_source=d.get("page_source"),
    )


def _tab_bar_from_dict(d: dict[str, Any]) -> TabBarElement:
    recurse = _from_dict_dispatch()
    tabs: list[dict[str, Any]] = [
        {
            "label": t.get("label", "Tab"),
            "children": [recurse(c) for c in t.get("children", [])],
        }
        for t in d.get("tabs", [])
    ]
    return TabBarElement(id=d["id"], tabs=tabs)


def _collapsing_header_from_dict(d: dict[str, Any]) -> CollapsingHeaderElement:
    recurse = _from_dict_dispatch()
    return CollapsingHeaderElement(
        id=d["id"],
        label=d.get("label", ""),
        default_open=d.get("default_open", False),
        children=[recurse(c) for c in d.get("children", [])],
    )


def _window_from_dict(d: dict[str, Any]) -> WindowElement:
    recurse = _from_dict_dispatch()
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
        children=[recurse(c) for c in d.get("children", [])],
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


def _modal_from_dict(d: dict[str, Any]) -> ModalElement:
    recurse = _from_dict_dispatch()
    return ModalElement(
        id=d["id"],
        title=d.get("title", ""),
        open=d.get("open", True),
        children=[recurse(c) for c in d.get("children", [])],
    )


SERIALIZERS: dict[type, Callable[..., dict[str, Any]]] = {
    GroupElement: _group_to_dict,
    TabBarElement: _tab_bar_to_dict,
    CollapsingHeaderElement: _collapsing_header_to_dict,
    WindowElement: _window_to_dict,
    TreeElement: _tree_to_dict,
    ModalElement: _modal_to_dict,
}

DESERIALIZERS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "group": _group_from_dict,
    "tab_bar": _tab_bar_from_dict,
    "collapsing_header": _collapsing_header_from_dict,
    "window": _window_from_dict,
    "tree": _tree_from_dict,
    "modal": _modal_from_dict,
}
