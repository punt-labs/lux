"""Layout container elements — group, tab-bar, headers, windows, modals, trees."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Self, cast

from punt_lux.domain.validation import ValidationError
from punt_lux.protocol.elements.codec import Register
from punt_lux.protocol.elements.container_dispatch import dispatch as _dispatchers

__all__ = [
    "LegacyCollapsingHeaderElement",
    "LegacyGroupElement",
    "LegacyTabBarElement",
    "ModalElement",
    "TreeElement",
    "WindowElement",
    "register_codecs",
]


@dataclass(frozen=True, slots=True)
class LegacyGroupElement:
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
        """Construct a LegacyGroupElement from a JSON-decoded mapping."""
        recurse = cls.decode_child
        pages_raw = d.get("pages", [])
        pages = [[recurse(e) for e in page] for page in pages_raw]
        return cls(
            id=d["id"],
            layout=d.get("layout", "rows"),
            children=[recurse(c) for c in d.get("children", [])],
            pages=pages,
            page_source=d.get("page_source"),
        )

    @staticmethod
    def decode_child(raw: dict[str, Any]) -> Any:
        """Decode one container child, forcing any nested container legacy.

        A legacy container must never hold an ABC container — the legacy
        render path has no adapter for one and would fall back to the
        ``[unsupported element]`` placeholder. Routing a nested ``group`` or
        ``collapsing_header`` straight to its legacy form keeps every
        conditionally-ABC container inside a legacy subtree legacy, so an ABC
        container can never nest inside a legacy one. Other children decode
        through the shared dispatcher, where migrated leaves (text, button, …)
        still decode to their ABC form.

        Shared by every legacy container codec in this module (tab-bar,
        window, header, modal) so the invariant holds at every nesting site.
        """
        kind = raw.get("kind")
        if kind == "group":
            return LegacyGroupElement.from_dict(raw)
        if kind == "collapsing_header":
            return LegacyCollapsingHeaderElement.from_dict(raw)
        if kind == "tab_bar":
            return LegacyTabBarElement.from_dict(raw)
        return _dispatchers.from_dict(raw)


@dataclass(frozen=True, slots=True)
class LegacyTabBarElement:
    """A tabbed container. Each tab has a label and child elements.

    The legacy dataclass path (fork-don't-mix, DES-041): a ``tab_bar`` whose
    subtree is not entirely migrated-ABC, or one nested inside a legacy
    container, decodes onto this class. The ABC ``TabBarElement`` takes the
    canonical name.
    """

    id: str
    kind: Literal["tab_bar"] = "tab_bar"
    tabs: list[dict[str, Any]] = field(default_factory=lambda: list[dict[str, Any]]())
    tooltip: str | None = None

    def child_elements(self) -> tuple[object, ...]:
        """Return every tab's children for the validation walk."""
        return tuple(c for tab in self.tabs for c in tab.get("children", []))

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
        """Construct a LegacyTabBarElement from a JSON-decoded mapping."""
        recurse = LegacyGroupElement.decode_child
        tabs: list[dict[str, Any]] = [
            {
                "label": t.get("label", "Tab"),
                "children": [recurse(c) for c in t.get("children", [])],
            }
            for t in d.get("tabs", [])
        ]
        return cls(id=d["id"], tabs=tabs)


@dataclass(frozen=True, slots=True)
class LegacyCollapsingHeaderElement:
    """A collapsible section with a label and child elements.

    The legacy dataclass path (fork-don't-mix, DES-041): a
    ``collapsing_header`` whose subtree is not entirely migrated-ABC, or one
    nested inside a legacy container, decodes onto this class. The ABC
    ``CollapsingHeaderElement`` takes the canonical name.
    """

    id: str
    kind: Literal["collapsing_header"] = "collapsing_header"
    label: str = ""
    default_open: bool = False
    children: list[Any] = field(default_factory=lambda: list[Any]())
    tooltip: str | None = None

    def child_elements(self) -> tuple[object, ...]:
        """Return direct children for the validation walk."""
        return tuple(self.children)

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
        recurse = LegacyGroupElement.decode_child
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

    def child_elements(self) -> tuple[object, ...]:
        """Return direct children for the validation walk."""
        return tuple(self.children)

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
        recurse = LegacyGroupElement.decode_child
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

    def child_elements(self) -> tuple[object, ...]:
        """Return no child elements — a tree's nodes are plain mappings.

        Tree nodes carry ``label`` / ``children`` data, not nested Lux
        elements, so the walk has nothing to recurse into. The node
        structure is checked by :meth:`validate` instead.
        """
        return ()

    def validate(self) -> tuple[ValidationError, ...]:
        """Return errors where a node is not a labeled mapping.

        Component-appropriate structural check for a *tree*: every node
        must be a mapping carrying a string ``label``, and a node's
        optional ``children`` must be a list obeying the same rule at
        every depth. Malformed nodes are reported, never dropped.
        """
        return tuple(self._node_errors(self.nodes))

    def _node_errors(self, nodes: object) -> list[ValidationError]:
        """Return errors for a node list, recursing into each node's children."""
        if not isinstance(nodes, list):
            return [self._error("nodes must be a list of nodes")]
        errors: list[ValidationError] = []
        for index, node in enumerate(cast("list[object]", nodes)):
            errors.extend(self._one_node_errors(node, index))
        return errors

    def _one_node_errors(self, node: object, index: int) -> list[ValidationError]:
        """Return errors for a single node at ``index``, recursing into children."""
        if not isinstance(node, dict):
            return [self._error(f"node {index} is not a mapping")]
        mapping = cast("dict[str, object]", node)
        errors: list[ValidationError] = []
        if not isinstance(mapping.get("label"), str):
            errors.append(self._error(f"node {index} is missing a string 'label'"))
        children = mapping.get("children")
        if children is not None:
            errors.extend(self._node_errors(children))
        return errors

    def _error(self, message: str) -> ValidationError:
        """Build a tree ValidationError carrying this tree's identity."""
        return ValidationError(
            element_id=self.id,
            element_kind=self.kind,
            message=message,
        )

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
        """Construct a TreeElement from a JSON-decoded mapping.

        Nodes are stored as received — malformed nodes are surfaced by
        :meth:`validate` before render, not silently discarded here.
        """
        return cls(
            id=d["id"],
            label=d.get("label", ""),
            nodes=d.get("nodes", []),
            flat=d.get("flat", False),
        )


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

    def child_elements(self) -> tuple[object, ...]:
        """Return direct children for the validation walk."""
        return tuple(self.children)

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
        recurse = LegacyGroupElement.decode_child
        return cls(
            id=d["id"],
            title=d.get("title", ""),
            open=d.get("open", True),
            children=[recurse(c) for c in d.get("children", [])],
        )


def register_codecs(register: Register) -> None:
    """Register this module's element codecs into an ElementCodec."""
    register(
        "group",
        LegacyGroupElement,
        LegacyGroupElement.to_dict,
        LegacyGroupElement.from_dict,
    )
    register(
        "tab_bar",
        LegacyTabBarElement,
        LegacyTabBarElement.to_dict,
        LegacyTabBarElement.from_dict,
    )
    register(
        "collapsing_header",
        LegacyCollapsingHeaderElement,
        LegacyCollapsingHeaderElement.to_dict,
        LegacyCollapsingHeaderElement.from_dict,
    )
    register("window", WindowElement, WindowElement.to_dict, WindowElement.from_dict)
    register("tree", TreeElement, TreeElement.to_dict, TreeElement.from_dict)
    register("modal", ModalElement, ModalElement.to_dict, ModalElement.from_dict)
