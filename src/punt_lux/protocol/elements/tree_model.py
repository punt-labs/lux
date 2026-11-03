"""TreeModel -- everything a tree is: its identity, its look and its content."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Self, final

from punt_lux.protocol.elements.patch_field import PatchField

if TYPE_CHECKING:
    from punt_lux.protocol.elements.tree_selection_facade import (
        TreeNodesState,
        TreeSelectionModel,
    )

__all__ = ["TreeModel"]


@final
@dataclass(frozen=True, slots=True)
class TreeModel:
    """The data of one tree, replaced whole by every patch.

    ``content`` is the nodes and the selection over them; the rest is how the tree
    presents itself. Each method named for a patch field (``labelled``, ``flattened``,
    ``tipped``, ``anchored``) coerces the value the patch carries, so the element
    holds no coercion of its own; ``with_content`` takes a typed value already made.

    PY-TS-14 OK: only ``tooltip`` is ``str | None``; absence is its documented
    contract.
    """

    id: str
    content: TreeNodesState
    label: str = ""
    flat: bool = False
    tooltip: str | None = None

    @property
    def selection(self) -> TreeSelectionModel:
        """The selection over the tree's nodes."""
        return self.content.selection

    def with_content(self, content: TreeNodesState) -> Self:
        """Return the model holding ``content`` in place of its own."""
        return replace(self, content=content)

    def anchored(self, value: object) -> Self:
        """Return the model with the selection anchor a patch carries."""
        anchor = PatchField("anchor_node_id").as_str(value)
        return self.with_content(self.content.anchored(anchor))

    def labelled(self, value: object) -> Self:
        """Return the model with the label a patch carries."""
        return replace(self, label=PatchField("label").as_str(value))

    def flattened(self, value: object) -> Self:
        """Return the model with the flatness a patch carries."""
        return replace(self, flat=PatchField("flat").as_bool(value))

    def tipped(self, value: object) -> Self:
        """Return the model with the tooltip a patch carries."""
        return replace(self, tooltip=PatchField("tooltip").as_optional_str(value))

    def resolved_props(self) -> dict[str, object]:
        """The fields as the introspection API reports them."""
        return {
            "label": self.label,
            "flat": self.flat,
            "tooltip": self.tooltip,
            **self.content.resolved_props(),
        }
