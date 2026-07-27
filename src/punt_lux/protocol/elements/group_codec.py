"""JsonGroupDecoder + JsonGroupEncoder — wire codec for the ABC GroupElement.

A ``group`` renders only a ``rows`` or ``columns`` stack. The decoder
validates the layout at the boundary (PY-EH-1) and rejects the removed
``paged`` layout and its ``pages`` / ``page_source`` wire fields with a
named error. Child recursion is injected (the tier's ``element_from_dict``)
so a nested group decodes exactly as the top-level factory would.
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

# Injected child decoder: the tier's ``element_from_dict`` bound method.
# It takes a wire dict and returns the decoded element. ``Any`` return
# matches the factory's heterogeneous element union.
type DecodeElement = Callable[[dict[str, Any]], object]

# The two layouts a group renders. The removed ``paged`` layout is rejected.
_STACK_LAYOUTS = frozenset({"rows", "columns"})


class JsonGroupDecoder:
    """Decode a wire dict to a fully-constructed ABC ``GroupElement``.

    Constructed with the tier's child decoder and the concrete element
    class. ``decode`` validates the layout and rejects the removed ``paged``
    layout at the boundary (PY-EH-1).
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

    def decode(self, raw: Mapping[str, object]) -> GroupElement:
        """Construct a GroupElement, recursing children through the tier decoder.

        Validates the layout at the boundary and rejects the removed ``paged``
        layout and its ``pages`` / ``page_source`` wire fields with a named
        error (PY-EH-1), before any child is decoded.
        """
        ctx = ElementWireContext.for_kind("group")
        group_id = ctx.require_id(raw)
        layout = ctx.optional_str(raw, "layout", default="rows")
        self._reject_removed_paged(group_id, layout, raw)
        children = ctx.decode_children(
            group_id, self._as_list(raw.get("children")), self._decode
        )
        return self._cls(
            id=group_id,
            layout=cast("Layout", layout),
            children=children,
            tooltip=ctx.optional_nullable_str(raw, "tooltip"),
        )

    @staticmethod
    def _reject_removed_paged(
        group_id: str, layout: str, raw: Mapping[str, object]
    ) -> None:
        """Raise if ``raw`` uses the removed paged layout or its wire fields."""
        if layout not in _STACK_LAYOUTS:
            msg = (
                f"group {group_id!r}: unknown layout {layout!r}; expected "
                f"'rows' or 'columns' (the 'paged' layout was removed)"
            )
            raise ValueError(msg)
        for field in ("pages", "page_source"):
            if field in raw:
                # Reject on PRESENCE, not truthiness: an empty ``{"pages": []}``
                # or ``{"page_source": ""}`` still names the removed paged layout
                # and must not decode as a plain stack group.
                msg = (
                    f"group {group_id!r}: {field!r} is no longer supported "
                    f"(the 'paged' layout was removed)"
                )
                raise ValueError(msg)

    def _decode(self, raw_child: object) -> Element:
        """Decode one wire child through the injected tier decoder."""
        child = cast("dict[str, Any]", raw_child)
        return cast("Element", self._decode_element(child))

    @staticmethod
    def _as_list(raw: object) -> list[object]:
        """Return ``raw`` as a list; ``[]`` when absent, raising a present non-list.

        Mirrors the window/modal codecs: an absent ``children`` is an empty group,
        but a present non-list (``"children": 5``) is a malformed wire tree and
        fails loud rather than silently dropping the subtree.
        """
        if raw is None:
            return []
        if not isinstance(raw, list):
            msg = f"group children must be a list, got {type(raw).__name__}"
            raise TypeError(msg)
        return cast("list[object]", raw)


class JsonGroupEncoder:
    """Encode an ABC ``GroupElement`` to its JSON-compatible wire dict.

    Stateless. Emits ``layout`` and ``children`` always, ``tooltip`` only
    when set — a group carries no other wire fields.
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
