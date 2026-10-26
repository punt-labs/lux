"""TreeElement — a collapsible tree on the Element ABC with Hub-authoritative selection.

Selection lives behind ``tree_selection_facade`` (PL-CU-1); codec in ``tree_codec.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Literal, Self, final

from punt_lux.domain.element_abc import Element
from punt_lux.domain.setter_priority import SetterPriority
from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.tree_codec import JsonTreeDecoder, JsonTreeEncoder
from punt_lux.protocol.elements.tree_model import TreeModel
from punt_lux.protocol.elements.tree_selection_facade import (
    TreeNodesState,
    TreeSelectionModel,
    TreeValidator,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.domain.validation import ValidationError
    from punt_lux.protocol.elements.tree_node import TreeNode
    from punt_lux.protocol.elements.tree_selection_facade import SelectionMode
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["TreeElement"]


@final
class TreeElement(Element):
    """A collapsible tree of recursive ``TreeNode`` values with an optional selection.

    The selection setters intersect against the live ids the node setter computes,
    so a patch's nodes are applied first whatever order its keys came in.

    PY-TS-14 OK: only ``tooltip`` is ``str | None``; every other field is total.
    """

    _SETTER_PRIORITY: ClassVar[SetterPriority] = SetterPriority(
        ("nodes", "selected_node_ids", "anchor_node_id")
    )
    _model: TreeModel

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory = RAISING_FACTORY,
        emit: Emit = NO_EMIT,
        id: str,
        label: str = "",
        nodes: tuple[TreeNode, ...] = (),
        flat: bool = False,
        tooltip: str | None = None,
        selection_mode: SelectionMode = "none",
        selected_node_ids: frozenset[str] = frozenset(),
        anchor_node_id: str = "",
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        sel = TreeSelectionModel(
            mode=selection_mode, selected=selected_node_ids, anchor=anchor_node_id
        )
        self._model = TreeModel(
            id=id,
            content=TreeNodesState(nodes=nodes, selection=sel),
            label=label,
            flat=flat,
            tooltip=tooltip,
        )
        return self

    @property
    def id(self) -> str:
        return self._model.id

    @property
    def kind(self) -> Literal["tree"]:
        return "tree"

    @property
    def label(self) -> str:
        return self._model.label

    @property
    def nodes(self) -> tuple[TreeNode, ...]:
        return self._model.content.nodes

    @property
    def flat(self) -> bool:
        return self._model.flat

    @property
    def tooltip(self) -> str | None:
        return self._model.tooltip

    @property
    def selection_mode(self) -> SelectionMode:
        return self._model.selection.mode

    @property
    def selected_node_ids(self) -> frozenset[str]:
        return self._model.selection.selected_node_ids

    @property
    def anchor_node_id(self) -> str:
        return self._model.selection.anchor

    def _set_label(self, value: object) -> None:
        self._model = self._model.labelled(value)

    def _set_nodes(self, value: object) -> None:
        before = self._model.selection
        content = self._model.content.replaced_nodes(value)
        self._model = self._model.with_content(content)
        self._notify_observers("nodes")
        content.selection.notify_if_changed(before, self._notify_observers)

    def _set_flat(self, value: object) -> None:
        self._model = self._model.flattened(value)

    def _set_tooltip(self, value: object) -> None:
        self._model = self._model.tipped(value)

    def _set_selected_node_ids(self, value: object) -> None:
        content = self._model.content.selected_from_wire(value)
        self._model = self._model.with_content(content)
        self._notify_observers("selected_node_ids")

    def _set_anchor_node_id(self, value: object) -> None:
        self._model = self._model.anchored(value)
        self._notify_observers("selected_node_ids")

    def validate(self) -> tuple[ValidationError, ...]:  # DES-039
        return TreeValidator(self).errors()

    def to_dict(self) -> dict[str, object]:
        return JsonTreeEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> TreeElement:
        decoder = JsonTreeDecoder(
            renderer_factory=RAISING_FACTORY, emit=NO_EMIT, element_cls=cls
        )
        return decoder.decode(d)

    def resolved_props(self) -> Mapping[str, object]:
        return self._model.resolved_props()
