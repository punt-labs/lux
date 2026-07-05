"""JsonGroupDecoder + JsonGroupEncoder — wire codec for the ABC GroupElement.

The decoder carries the **all-ABC gate** (``is_all_abc``, a pure function
of the wire dict) that forks a ``group`` onto the ABC path: a wire
``group`` decodes to :class:`GroupElement` only when its layout is a stack
(rows / columns) and its whole subtree is migrated-ABC. Any legacy
descendant, a ``paged`` layout, or paged wire fields force the subtree
onto :class:`LegacyGroupElement`, which owns ``pages`` / ``page_source``;
the ABC group has none. Child recursion is injected (the tier's
``element_from_dict``) so a nested all-ABC group decodes exactly as the
top-level factory would.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, Self, cast

from punt_lux.protocol.elements.container_dispatch import dispatch
from punt_lux.protocol.elements.element_wire import ElementWireContext

if TYPE_CHECKING:
    from punt_lux.domain.element_abc import Element
    from punt_lux.protocol.elements.group import GroupElement, Layout

__all__ = ["JsonGroupDecoder", "JsonGroupEncoder"]

# The wire kinds that decode onto the Element ABC. A group is all-ABC only
# when every element in its subtree is one of these AND every nested group
# is itself all-ABC with a stack layout.
_MIGRATED_ABC_KINDS = frozenset(
    {"text", "button", "checkbox", "dialog", "group", "progress"}
)

# The two layouts an ABC group renders; ``paged`` stays on the legacy path.
_STACK_LAYOUTS = frozenset({"rows", "columns"})

# Injected child decoder: the tier's ``element_from_dict`` bound method.
# It takes a wire dict and returns the decoded element (ABC for an all-ABC
# subtree). ``Any`` return matches the factory's heterogeneous element union.
type DecodeElement = Callable[[dict[str, Any]], object]


class JsonGroupDecoder:
    """Decode a wire dict to a fully-constructed ABC ``GroupElement``.

    Constructed with the tier's child decoder and the concrete element
    class. ``is_all_abc`` is the gate the factory consults to decide
    whether a ``group`` forks onto this decoder or the legacy container.
    """

    _decode_element: DecodeElement
    _cls: type[GroupElement]

    def __new__(
        cls,
        *,
        decode_element: DecodeElement,
        element_cls: type[GroupElement],
    ) -> Self:
        self = super().__new__(cls)
        self._decode_element = decode_element
        self._cls = element_cls
        return self

    @classmethod
    def is_all_abc(cls, raw: Mapping[str, object]) -> bool:
        """Return whether ``raw`` is an all-ABC, stack-layout group subtree."""
        return cls.first_non_abc_kind(raw) is None

    @classmethod
    def first_non_abc_kind(cls, raw: Mapping[str, object]) -> str | None:
        """Return the first reason ``raw`` forks legacy, or ``None`` if it is
        an all-ABC stack group. A non-stack ``layout``, a legacy descendant
        ``kind``, or non-empty ``pages`` / ``page_source`` (panels the ABC
        group cannot hold) each fork legacy; empty paged fields decode ABC.
        """
        layout = raw.get("layout", "rows")
        if layout not in _STACK_LAYOUTS:
            return f"layout={layout!r}"
        if raw.get("pages"):
            return "pages"
        if raw.get("page_source"):
            return "page_source"
        for elem in cls._subtree(raw):
            reason = cls._child_non_abc_reason(elem)
            if reason is not None:
                return reason
        return None

    @classmethod
    def _child_non_abc_reason(cls, raw_child: object) -> str | None:
        """Return why one wire child is not all-ABC, or ``None`` if it is."""
        if not isinstance(raw_child, Mapping):
            return f"non-mapping child {raw_child!r}"
        child = cast("Mapping[str, object]", raw_child)
        kind = child.get("kind")
        if kind not in _MIGRATED_ABC_KINDS:
            return str(kind)
        if kind == "group":
            return cls.first_non_abc_kind(child)
        return None

    @staticmethod
    def _subtree(raw: Mapping[str, object]) -> tuple[object, ...]:
        """Return the group's direct children."""
        return tuple(_as_list(raw.get("children")))

    def decode(self, raw: Mapping[str, object]) -> GroupElement:
        """Construct a GroupElement, recursing children through the tier decoder."""
        ctx = ElementWireContext.for_kind("group")
        children = tuple(self._decode(c) for c in _as_list(raw.get("children")))
        layout = cast("Layout", ctx.optional_str(raw, "layout", default="rows"))
        return self._cls(
            id=ctx.require_str(raw, "id"),
            layout=layout,
            children=children,
            tooltip=ctx.optional_nullable_str(raw, "tooltip"),
        )

    def _decode(self, raw_child: object) -> Element:
        """Decode one wire child through the injected tier decoder."""
        child = cast("dict[str, Any]", raw_child)
        return cast("Element", self._decode_element(child))


class JsonGroupEncoder:
    """Encode an ABC ``GroupElement`` to its JSON-compatible wire dict.

    Stateless. Emits the identical wire shape the legacy group produced for
    a rows/columns group — ``layout`` and ``children`` always, ``tooltip``
    only when set (a stack group has no paged fields) — so an all-ABC group
    re-encodes byte-for-byte.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode(self, elem: GroupElement) -> dict[str, object]:
        """Serialize a GroupElement to a JSON-compatible dict."""
        recurse = dispatch.to_dict
        payload: dict[str, object] = {
            "kind": "group",
            "id": elem.id,
            "layout": elem.layout,
            "children": [recurse(child) for child in elem.children],
        }
        if elem.tooltip is not None:
            payload["tooltip"] = elem.tooltip
        return payload


def _as_list(raw: object) -> list[object]:
    """Return ``raw`` as a list of wire objects, or empty when absent/other."""
    if isinstance(raw, list):
        return cast("list[object]", raw)
    return []
