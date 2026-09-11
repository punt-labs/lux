"""JsonTreeDecoder + JsonTreeEncoder — wire codec for ``TreeElement``.

Sibling module, not methods on ``TreeElement``, so ``to_dict``/``from_dict``
stay short Protocol-satisfying delegators. ``TreeNode.decode_all`` rejects a
malformed node (PY-EH-1) before construction. Selection wire fields route
through ``SelectionWire``, shared with ``table_codec.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.protocol.elements._util import strip_none
from punt_lux.protocol.elements.element_wire import ElementWireContext
from punt_lux.protocol.elements.selection_wire import SelectionWire
from punt_lux.protocol.elements.tree_node import TreeNode

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.elements.tree import TreeElement
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["JsonTreeDecoder", "JsonTreeEncoder"]


class JsonTreeDecoder:
    """Decode a wire dict to a fully-constructed ``TreeElement``.

    Constructed once per tier with that tier's injected ``renderer_factory`` + ``emit``.
    """

    _rf: RendererFactory
    _emit: Emit
    _cls: type[TreeElement]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        element_cls: type[TreeElement],
    ) -> Self:
        self = super().__new__(cls)
        self._rf = renderer_factory
        self._emit = emit
        self._cls = element_cls
        return self

    def decode(self, raw: Mapping[str, object]) -> TreeElement:
        ctx = ElementWireContext.for_kind("tree")
        return self._cls(
            renderer_factory=self._rf,
            emit=self._emit,
            id=ctx.require_id(raw),
            label=ctx.optional_str(raw, "label", default=""),
            nodes=TreeNode.decode_all(raw.get("nodes", []), "nodes"),
            flat=ctx.optional_bool(raw, "flat", default=False),
            tooltip=ctx.optional_nullable_str(raw, "tooltip"),
            selection_mode=SelectionWire.decode_mode(raw.get("selection_mode", "none")),
            selected_node_ids=frozenset(
                ctx.optional_string_list(raw, "selected_node_ids")
            ),
            anchor_node_id=ctx.optional_str(raw, "anchor_node_id", default=""),
        )


class JsonTreeEncoder:
    """Encode a ``TreeElement`` to its JSON-compatible wire dict, stateless."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode(self, elem: TreeElement) -> dict[str, object]:
        payload = strip_none(
            {
                "kind": elem.kind,
                "id": elem.id,
                "label": elem.label,
                "nodes": [node.to_dict() for node in elem.nodes],
                "flat": elem.flat or None,
                "tooltip": elem.tooltip,
            }
        )
        SelectionWire.emit_fields(
            payload,
            mode=elem.selection_mode,
            selected_ids=elem.selected_node_ids,
            anchor_id=elem.anchor_node_id,
            noun="node",
        )
        return payload
