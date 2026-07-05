"""JsonGroupDecoder + JsonGroupEncoder — wire codec for the ABC GroupElement.

The decoder carries the **all-ABC gate** that forks a ``group`` onto the
ABC path: a wire ``group`` decodes to :class:`GroupElement` only when its
entire subtree is a migrated-ABC kind and its layout is a stack (rows /
columns). Any legacy descendant, or a ``paged`` layout, forces the whole
subtree onto the legacy container instead. The gate is a pure function of
the wire dict (``is_all_abc``) so the tier factory can consult it before
choosing a decoder.

Child recursion is injected, not imported: the decoder is handed the
tier's ``element_from_dict`` so a nested all-ABC group decodes to ABC
children exactly as the top-level factory would.
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
_MIGRATED_ABC_KINDS = frozenset({"text", "button", "checkbox", "dialog", "group"})

# The two layouts an ABC group renders this migration; ``paged`` stays legacy.
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
        """Return whether ``raw`` is an all-ABC, stack-layout group subtree.

        True iff the group's layout is rows/columns and every element in
        its subtree (children and paged panels, recursively for nested
        groups) is a migrated-ABC kind. Any legacy kind anywhere, or a
        paged layout at any depth, yields False.
        """
        if raw.get("layout", "rows") not in _STACK_LAYOUTS:
            return False
        return all(cls._element_is_abc(elem) for elem in cls._subtree(raw))

    @classmethod
    def _element_is_abc(cls, raw_child: object) -> bool:
        """Return whether one wire child (and its subtree) is all-ABC."""
        if not isinstance(raw_child, Mapping):
            return False
        child = cast("Mapping[str, object]", raw_child)
        kind = child.get("kind")
        if kind not in _MIGRATED_ABC_KINDS:
            return False
        if kind == "group":
            return cls.is_all_abc(child)
        return True

    @staticmethod
    def _subtree(raw: Mapping[str, object]) -> tuple[object, ...]:
        """Return the group's direct children and every paged element."""
        elems: list[object] = []
        elems.extend(_as_list(raw.get("children")))
        for page in _as_list(raw.get("pages")):
            elems.extend(_as_list(page))
        return tuple(elems)

    def decode(self, raw: Mapping[str, object]) -> GroupElement:
        """Construct a GroupElement, recursing children through the tier decoder."""
        ctx = ElementWireContext.for_kind("group")
        children = tuple(self._decode(c) for c in _as_list(raw.get("children")))
        pages = tuple(
            tuple(self._decode(e) for e in _as_list(page))
            for page in _as_list(raw.get("pages"))
        )
        layout = cast("Layout", ctx.optional_str(raw, "layout", default="rows"))
        return self._cls(
            id=ctx.require_str(raw, "id"),
            layout=layout,
            children=children,
            pages=pages,
            page_source=ctx.optional_str(raw, "page_source", default=""),
            tooltip=ctx.optional_nullable_str(raw, "tooltip"),
        )

    def _decode(self, raw_child: object) -> Element:
        """Decode one wire child through the injected tier decoder."""
        child = cast("dict[str, Any]", raw_child)
        return cast("Element", self._decode_element(child))


class JsonGroupEncoder:
    """Encode an ABC ``GroupElement`` to its JSON-compatible wire dict.

    Stateless. Emits the identical wire shape the legacy group produced —
    ``layout`` and ``children`` always, ``pages`` / ``page_source`` /
    ``tooltip`` only when set — so an all-ABC group re-encodes byte-for-byte.
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
        if elem.pages:
            payload["pages"] = [[recurse(e) for e in page] for page in elem.pages]
        if elem.page_source:
            payload["page_source"] = elem.page_source
        if elem.tooltip is not None:
            payload["tooltip"] = elem.tooltip
        return payload


def _as_list(raw: object) -> list[object]:
    """Return ``raw`` as a list of wire objects, or empty when absent/other."""
    if isinstance(raw, list):
        return cast("list[object]", raw)
    return []
