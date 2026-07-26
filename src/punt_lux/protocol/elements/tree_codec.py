"""JsonTreeDecoder + JsonTreeEncoder — wire codec for ``TreeElement``.

The codec body lives in this sibling module rather than on ``TreeElement``.
``TreeElement.to_dict`` / ``TreeElement.from_dict`` remain as short delegators
so the runtime-checkable ``domain.element.Element`` Protocol stays satisfied.

The decoder injects the tier's ``renderer_factory`` + ``emit`` at construction;
off the display tier that is the fail-loud sentinel, which the Display rebinds
post-receive. Malformed nodes are rejected here at the boundary (PY-EH-1) via
``TreeNode.decode_all`` — a non-mapping or label-less node raises ``ValueError``
before the element is built, so a tree can carry only well-formed nodes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.protocol.elements._util import strip_none
from punt_lux.protocol.elements.element_wire import ElementWireContext
from punt_lux.protocol.elements.tree_node import TreeNode

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.elements.tree import TreeElement
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["JsonTreeDecoder", "JsonTreeEncoder"]


class JsonTreeDecoder:
    """Decode a wire dict to a fully-constructed ``TreeElement``.

    Constructed once per tier with that tier's ``renderer_factory`` + ``emit``;
    every decoded element is born with the same injected DI. Boundary validation
    (PY-EH-1) routes through ``ElementWireContext`` and ``TreeNode.decode_all`` so
    a non-string ``id``/``label`` or a malformed node raises a typed ``ValueError``
    naming the offending field or node position.
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
        """Construct a TreeElement from a JSON-decoded mapping."""
        ctx = ElementWireContext.for_kind("tree")
        return self._cls(
            renderer_factory=self._rf,
            emit=self._emit,
            id=ctx.require_id(raw),
            label=ctx.optional_str(raw, "label", default=""),
            nodes=TreeNode.decode_all(raw.get("nodes", []), "nodes"),
            flat=ctx.optional_bool(raw, "flat", default=False),
            tooltip=ctx.optional_nullable_str(raw, "tooltip"),
        )


class JsonTreeEncoder:
    """Encode a ``TreeElement`` to its JSON-compatible wire dict.

    Stateless. ``flat`` is omitted when falsy and ``tooltip`` when ``None``
    (an empty-string tooltip is still serialized), matching the legacy
    dataclass codec byte-for-byte; ``label`` and ``nodes`` are always emitted.
    """

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode(self, elem: TreeElement) -> dict[str, object]:
        """Serialize a TreeElement to a JSON-compatible dict."""
        return strip_none(
            {
                "kind": elem.kind,
                "id": elem.id,
                "label": elem.label,
                "nodes": [node.to_dict() for node in elem.nodes],
                "flat": elem.flat or None,
                "tooltip": elem.tooltip,
            }
        )
