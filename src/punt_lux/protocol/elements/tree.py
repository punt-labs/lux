"""Define a collapsible tree with Hub-authoritative selection."""

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
    """Render recursive nodes with an optional selection.

    A patch applies nodes before selection, regardless of key order, so a
    selection can only refer to nodes that survive the patch.
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
        """Return the element ID used by scene updates."""
        return self._model.id

    @property
    def kind(self) -> Literal["tree"]:
        """Return the tree's wire discriminator."""
        return "tree"

    @property
    def label(self) -> str:
        """Return the visible tree label."""
        return self._model.label

    @property
    def nodes(self) -> tuple[TreeNode, ...]:
        """Return the root nodes in display order."""
        return self._model.content.nodes

    @property
    def flat(self) -> bool:
        """Report whether the tree renders as a flat list."""
        return self._model.flat

    @property
    def tooltip(self) -> str | None:
        """Return hover text, or None when no tooltip is configured."""
        return self._model.tooltip

    @property
    def selection_mode(self) -> SelectionMode:
        """Return the tree's selection policy."""
        return self._model.selection.mode

    @property
    def selected_node_ids(self) -> frozenset[str]:
        """Return the IDs of selected nodes, including hidden descendants."""
        return self._model.selection.selected_node_ids

    @property
    def anchor_node_id(self) -> str:
        """Return the range-selection anchor, or an empty string if unset."""
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
        """Report invalid node and selection state without changing it."""
        return TreeValidator(self).errors()

    def to_dict(self) -> dict[str, object]:
        """Encode the tree's public fields for the wire."""
        return JsonTreeEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> TreeElement:
        """Decode wire fields into a tree without display-side bindings."""
        decoder = JsonTreeDecoder(
            renderer_factory=RAISING_FACTORY, emit=NO_EMIT, element_cls=cls
        )
        return decoder.decode(d)

    def resolved_props(self) -> Mapping[str, object]:
        """Return the normalized properties reported by scene inspection."""
        return self._model.resolved_props()
