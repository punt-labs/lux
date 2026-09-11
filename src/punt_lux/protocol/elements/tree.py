"""TreeElement — a collapsible tree on the Element ABC with Hub-authoritative selection.

Selection machinery (``TreeNodesState``/``TreeSelectionModel``/``TreeValidator``)
is reached via ``tree_selection_facade`` (PL-CU-1); codec in ``tree_codec.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, cast

from punt_lux.domain.element_abc import Element
from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.patch_field import PatchField
from punt_lux.protocol.elements.tree_codec import JsonTreeDecoder, JsonTreeEncoder
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


class TreeElement(Element):
    """A collapsible tree of recursive ``TreeNode`` values with an optional selection.

    PY-TS-14 OK: only ``tooltip`` is ``str | None``; every other field is total.
    """

    _id: str
    _label: str
    _state: TreeNodesState
    _flat: bool
    _tooltip: str | None
    _kind: Literal["tree"]

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
        self._id = id
        self._label = label
        sel = TreeSelectionModel(
            mode=selection_mode, selected=selected_node_ids, anchor=anchor_node_id
        )
        self._state = TreeNodesState(nodes=nodes, selection=sel)
        self._flat = flat
        self._tooltip = tooltip
        self._kind = "tree"
        return self

    @property
    def id(self) -> str:
        return self._id

    @property
    def kind(self) -> Literal["tree"]:
        return self._kind

    @property
    def label(self) -> str:
        return self._label

    @property
    def nodes(self) -> tuple[TreeNode, ...]:
        return self._state.nodes

    @property
    def flat(self) -> bool:
        return self._flat

    @property
    def tooltip(self) -> str | None:
        return self._tooltip

    @property
    def selection_mode(self) -> SelectionMode:
        return self._state.selection.mode

    @property
    def selected_node_ids(self) -> frozenset[str]:
        return self._state.selection.selected_node_ids

    @property
    def anchor_node_id(self) -> str:
        return self._state.selection.anchor

    def _set_label(self, value: object) -> None:
        self._label = PatchField("label").as_str(value)

    def _set_nodes(self, value: object) -> None:
        before = self._state.selection
        self._state = self._state.replaced_nodes(value)
        self._notify_observers("nodes")
        self._state.selection.notify_if_changed(before, self._notify_observers)

    def _set_flat(self, value: object) -> None:
        self._flat = PatchField("flat").as_bool(value)

    def _set_tooltip(self, value: object) -> None:
        self._tooltip = PatchField("tooltip").as_optional_str(value)

    def _set_selected_node_ids(self, value: object) -> None:
        self._state = self._state.selected_from_wire(value)
        self._notify_observers("selected_node_ids")

    def _set_anchor_node_id(self, value: object) -> None:
        node_id = PatchField("anchor_node_id").as_str(value)
        self._state = self._state.anchored(node_id)
        self._notify_observers("selected_node_ids")

    def validate(self) -> tuple[ValidationError, ...]:  # DES-039
        return TreeValidator(self).errors()

    def to_dict(self) -> dict[str, object]:
        return JsonTreeEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        decoder = JsonTreeDecoder(
            renderer_factory=RAISING_FACTORY, emit=NO_EMIT, element_cls=cls
        )
        return cast("Self", decoder.decode(d))  # element_cls=cls guarantees the subtype

    def resolved_props(self) -> Mapping[str, object]:
        return {
            "label": self._label,
            "flat": self._flat,
            "tooltip": self._tooltip,
            **self._state.resolved_props(),
        }
