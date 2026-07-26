"""Layout container elements — group, tab-bar, headers, windows, modals, trees."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, Self

from punt_lux.protocol.elements.codec import Register
from punt_lux.protocol.elements.container_dispatch import dispatch as _dispatchers

__all__ = [
    "LegacyCollapsingHeaderElement",
    "LegacyGroupElement",
    "LegacyModalElement",
    "LegacyTabBarElement",
    "LegacyWindowElement",
]


@dataclass(frozen=True, slots=True)
class LegacyGroupElement:
    """A layout container arranging children in rows, columns, or pages.

    ``rows`` (default) stacks vertically, ``columns`` side-by-side; ``paged`` is
    a combo-driven switcher where ``children`` stay visible (header/nav) and
    ``pages`` are indexed panels switched by the combo named in ``page_source``.
    """

    id: str
    kind: Literal["group"] = "group"
    layout: Literal["rows", "columns", "paged"] = "rows"
    children: list[Any] = field(default_factory=lambda: list[Any]())
    pages: list[list[Any]] = field(default_factory=lambda: list[list[Any]]())
    page_source: str | None = None  # id of ComboElement driving page index
    tooltip: str | None = None

    def child_elements(self) -> tuple[object, ...]:
        """Return direct children (visible plus every paged element) for the walk.

        An invalid element hidden on a non-active page is still installed and
        must be caught, so ``pages`` are walked too.
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
            d["pages"] = self._encoded_pages()
        if self.page_source is not None:
            d["page_source"] = self.page_source
        return d

    def _encoded_pages(self) -> list[list[dict[str, Any]]]:
        """Return the paged panels encoded to wire dicts, one list per page."""
        recurse = _dispatchers.to_dict
        return [[recurse(element) for element in page] for page in self.pages]

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

        A legacy container must never hold an ABC container (the legacy renderer
        has no adapter for one). Forcing a nested conditionally-ABC container to
        its legacy form keeps the whole subtree legacy; other children decode
        through the shared dispatcher, where migrated leaves still cross to ABC.
        """
        kind = raw.get("kind")
        forced = _LEGACY_CONTAINER_DECODERS.get(kind) if isinstance(kind, str) else None
        return forced(raw) if forced is not None else _dispatchers.from_dict(raw)

    @staticmethod
    def register_codecs(register: Register) -> None:
        """Register every legacy layout codec into an ElementCodec.

        Hosted here because ``LegacyGroupElement`` already owns the module's
        shared legacy machinery (``decode_child``); each still-legacy container
        registers its own codec triple until it forks onto the ABC path.
        """
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
        register(
            "window",
            LegacyWindowElement,
            LegacyWindowElement.to_dict,
            LegacyWindowElement.from_dict,
        )
        register(
            "modal",
            LegacyModalElement,
            LegacyModalElement.to_dict,
            LegacyModalElement.from_dict,
        )


@dataclass(frozen=True, slots=True)
class LegacyTabBarElement:
    """The legacy dataclass fork of ``tab_bar`` (fork-don't-mix).

    Decoded when a ``tab_bar``'s subtree is not all-ABC or it nests inside a
    legacy container; the ABC ``TabBarElement`` takes the canonical name.
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
    """The legacy dataclass fork of ``collapsing_header`` (fork-don't-mix).

    Decoded when the subtree is not all-ABC or it nests inside a legacy
    container; the ABC ``CollapsingHeaderElement`` takes the canonical name.
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
class LegacyWindowElement:
    """The legacy dataclass fork of ``window`` — a movable, resizable sub-window.

    Decoded when a ``window``'s subtree is not all-ABC or it nests inside a legacy
    container; the ABC ``WindowElement`` takes the canonical name.
    """

    # The bool window flags whose wire key is the attribute name; emitted only
    # when True. A data-driven tuple keeps ``to_dict`` a single comprehension
    # instead of one ``if`` per flag (PY-OO: dispatch on data, not a ladder).
    _OPTIONAL_FLAGS: ClassVar[tuple[str, ...]] = (
        "no_move",
        "no_resize",
        "no_collapse",
        "no_title_bar",
        "no_scrollbar",
        "auto_resize",
    )

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
        d.update({flag: True for flag in self._OPTIONAL_FLAGS if getattr(self, flag)})
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
class LegacyModalElement:
    """The legacy dataclass fork of ``modal`` (fork-don't-mix).

    Decoded when a ``modal``'s subtree is not entirely migrated-ABC or it nests
    inside a legacy container; the ABC ``ModalElement`` takes the canonical name.
    ``open=True`` shows the popup; the display emits ``"closed"`` on dismiss.
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


# Conditionally-ABC container kinds forced legacy when nested in a legacy subtree
# — data-driven (Open-Closed): a new such kind is one entry, not another branch.
_LEGACY_CONTAINER_DECODERS: dict[str, Callable[[dict[str, Any]], Any]] = {
    "group": LegacyGroupElement.from_dict,
    "collapsing_header": LegacyCollapsingHeaderElement.from_dict,
    "tab_bar": LegacyTabBarElement.from_dict,
    "modal": LegacyModalElement.from_dict,
    "window": LegacyWindowElement.from_dict,
}
