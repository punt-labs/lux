"""Layout container elements — group, tab-bar, headers, windows, modals, trees."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Self, cast

from punt_lux.protocol.elements.codec import Register

__all__ = [
    "CollapsingHeaderElement",
    "GroupElement",
    "ModalElement",
    "TabBarElement",
    "TreeElement",
    "WindowElement",
    "from_dict_dispatcher",
    "install_from_dict",
    "install_to_dict",
    "register_codecs",
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
    layout: Literal["rows", "columns", "paged"] = "rows"
    children: list[Any] = field(default_factory=lambda: list[Any]())
    pages: list[list[Any]] = field(default_factory=lambda: list[list[Any]]())
    page_source: str | None = None  # id of ComboElement driving page index
    tooltip: str | None = None

    def child_elements(self) -> tuple[object, ...]:
        """Return direct children for the validation walk.

        Includes both the always-visible ``children`` and every element
        across ``pages`` — an invalid element hidden on a non-active page
        is still installed into the scene and must be caught.
        """
        paged = [element for page in self.pages for element in page]
        return (*self.children, *paged)

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-compatible wire representation."""
        recurse = _dispatchers.to_dict
        d: dict[str, Any] = {
            "kind": self.kind,
            "id": self.id,
            "layout": self.layout,
            "children": [recurse(c) for c in self.children],
        }
        if self.pages:
            d["pages"] = [[recurse(e) for e in page] for page in self.pages]
        if self.page_source is not None:
            d["page_source"] = self.page_source
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """Construct a GroupElement from a JSON-decoded mapping."""
        recurse = _dispatchers.from_dict
        pages_raw = d.get("pages", [])
        pages = [[recurse(e) for e in page] for page in pages_raw]
        return cls(
            id=d["id"],
            layout=d.get("layout", "rows"),
            children=[recurse(c) for c in d.get("children", [])],
            pages=pages,
            page_source=d.get("page_source"),
        )


@dataclass(frozen=True, slots=True)
class TabBarElement:
    """A tabbed container. Each tab has a label and child elements."""

    id: str
    kind: Literal["tab_bar"] = "tab_bar"
    tabs: list[dict[str, Any]] = field(default_factory=lambda: list[dict[str, Any]]())
    tooltip: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-compatible wire representation."""
        recurse = _dispatchers.to_dict
        return {
            "kind": self.kind,
            "id": self.id,
            "tabs": [
                {
                    "label": t.get("label", "Tab"),
                    "children": [recurse(c) for c in t.get("children", [])],
                }
                for t in self.tabs
            ],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """Construct a TabBarElement from a JSON-decoded mapping."""
        recurse = _dispatchers.from_dict
        tabs: list[dict[str, Any]] = [
            {
                "label": t.get("label", "Tab"),
                "children": [recurse(c) for c in t.get("children", [])],
            }
            for t in d.get("tabs", [])
        ]
        return cls(id=d["id"], tabs=tabs)


@dataclass(frozen=True, slots=True)
class CollapsingHeaderElement:
    """A collapsible section with a label and child elements."""

    id: str
    kind: Literal["collapsing_header"] = "collapsing_header"
    label: str = ""
    default_open: bool = False
    children: list[Any] = field(default_factory=lambda: list[Any]())
    tooltip: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-compatible wire representation."""
        recurse = _dispatchers.to_dict
        d: dict[str, Any] = {
            "kind": self.kind,
            "id": self.id,
            "label": self.label,
            "children": [recurse(c) for c in self.children],
        }
        if self.default_open:
            d["default_open"] = True
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """Construct a CollapsingHeaderElement from a JSON-decoded mapping."""
        recurse = _dispatchers.from_dict
        return cls(
            id=d["id"],
            label=d.get("label", ""),
            default_open=d.get("default_open", False),
            children=[recurse(c) for c in d.get("children", [])],
        )


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

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-compatible wire representation."""
        recurse = _dispatchers.to_dict
        d: dict[str, Any] = {
            "kind": self.kind,
            "id": self.id,
            "title": self.title,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "children": [recurse(c) for c in self.children],
        }
        if self.no_move:
            d["no_move"] = True
        if self.no_resize:
            d["no_resize"] = True
        if self.no_collapse:
            d["no_collapse"] = True
        if self.no_title_bar:
            d["no_title_bar"] = True
        if self.no_scrollbar:
            d["no_scrollbar"] = True
        if self.auto_resize:
            d["auto_resize"] = True
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """Construct a WindowElement from a JSON-decoded mapping."""
        recurse = _dispatchers.from_dict
        return cls(
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

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-compatible wire representation."""
        d: dict[str, Any] = {
            "kind": self.kind,
            "id": self.id,
            "label": self.label,
            "nodes": self.nodes,
        }
        if self.flat:
            d["flat"] = True
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """Construct a TreeElement from a JSON-decoded mapping."""
        return cls(
            id=d["id"],
            label=d.get("label", ""),
            nodes=cls._normalize_nodes(d.get("nodes", [])),
            flat=d.get("flat", False),
        )

    @classmethod
    def _normalize_nodes(cls, raw: Any) -> list[dict[str, Any]]:
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
                node["children"] = cls._normalize_nodes(raw_children)
            result.append(node)
        return result


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

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-compatible wire representation."""
        recurse = _dispatchers.to_dict
        return {
            "kind": self.kind,
            "id": self.id,
            "title": self.title,
            "open": self.open,
            "children": [recurse(c) for c in self.children],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Self:
        """Construct a ModalElement from a JSON-decoded mapping."""
        recurse = _dispatchers.from_dict
        return cls(
            id=d["id"],
            title=d.get("title", ""),
            open=d.get("open", True),
            children=[recurse(c) for c in d.get("children", [])],
        )


# Container codecs recurse via the package-level dispatcher in
# protocol/elements/__init__.py. Importing element_to_dict /
# JsonElementFactory.element_from_dict at module import time would
# create a circular import — the aggregator imports this module to
# build the union and dispatch tables, so this module cannot import the
# dispatchers eagerly. The aggregator calls ``install_to_dict()`` once
# at import time with the encode-side function; each tier calls
# ``install_from_dict()`` at startup with its
# :meth:`JsonElementFactory.element_from_dict` bound method.
_RecurseToDict = Callable[[Any], dict[str, Any]]
_RecurseFromDict = Callable[[dict[str, Any]], Any]


class _DispatcherRegistry:
    """Holds the package-level encode/decode container recursion targets.

    A single shared instance lives at module scope. Encapsulating the
    two pointers in a class (instead of bare module-level globals)
    avoids the ``global`` statement and the corresponding
    ``PLW0603`` suppressions while preserving the install-once semantics
    container codecs need.
    """

    _to_dict: _RecurseToDict | None
    _from_dict: _RecurseFromDict | None

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._to_dict = None
        self._from_dict = None
        return self

    def install_to_dict(self, to_dict: _RecurseToDict) -> None:
        """Bind the encode-side container recursion function."""
        self._to_dict = to_dict

    def install_from_dict(self, from_dict: _RecurseFromDict) -> None:
        """Bind the decode-side container recursion function."""
        self._from_dict = from_dict

    @property
    def to_dict(self) -> _RecurseToDict:
        """Return the encode-side recursion function, or raise."""
        if self._to_dict is None:
            msg = "layout codecs used before encode dispatcher installed"
            raise RuntimeError(msg)
        return self._to_dict

    @property
    def from_dict(self) -> _RecurseFromDict:
        """Return the decode-side recursion function, or raise."""
        if self._from_dict is None:
            msg = (
                "layout codecs used before decode dispatcher installed — "
                "construct a JsonElementFactory at tier startup and call "
                "layout.install_from_dict(factory.element_from_dict)"
            )
            raise RuntimeError(msg)
        return self._from_dict


_dispatchers = _DispatcherRegistry()


def install_to_dict(to_dict: _RecurseToDict) -> None:
    """Inject the encode-side container recursion function.

    The encode side has no DI dependency — :mod:`elements` calls this
    once at import time with the module-level ``_element_to_dict``.
    """
    _dispatchers.install_to_dict(to_dict)


def install_from_dict(from_dict: _RecurseFromDict) -> None:
    """Inject the decode-side container recursion function.

    Each tier calls this once at startup with its
    :meth:`JsonElementFactory.element_from_dict` bound method, so the
    layout container codecs route child decode through the same
    tier-injected DI as the parent. No module-level default exists —
    a tier that forgets to install gets a ``RuntimeError`` from the
    decode dispatcher on the first container decode.
    """
    _dispatchers.install_from_dict(from_dict)


def from_dict_dispatcher() -> _RecurseFromDict:
    """Return the installed decode-side recursion function.

    Exposes the per-tier decode dispatcher so sibling protocol modules
    (e.g. :mod:`protocol.messages.scene`) can recurse via the same
    tier-injected factory without reaching into private state.
    """
    return _dispatchers.from_dict


def register_codecs(register: Register) -> None:
    """Register this module's element codecs into an ElementCodec."""
    register("group", GroupElement, GroupElement.to_dict, GroupElement.from_dict)
    register(
        "tab_bar",
        TabBarElement,
        TabBarElement.to_dict,
        TabBarElement.from_dict,
    )
    register(
        "collapsing_header",
        CollapsingHeaderElement,
        CollapsingHeaderElement.to_dict,
        CollapsingHeaderElement.from_dict,
    )
    register("window", WindowElement, WindowElement.to_dict, WindowElement.from_dict)
    register("tree", TreeElement, TreeElement.to_dict, TreeElement.from_dict)
    register("modal", ModalElement, ModalElement.to_dict, ModalElement.from_dict)
