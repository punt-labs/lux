"""TreeNode — a recursive ``label`` + ``children`` value in a ``tree`` element.

A tree's nodes are a value family, not elements — no id, no handlers, no
independent render — the same composition ruling the draw-command family
follows. Malformed nodes are rejected at the wire boundary (PY-EH-1): a
non-mapping node, or one missing a string ``label``, raises ``ValueError``
before any ``TreeElement`` is constructed, so the renderer only ever walks
well-formed nodes and needs no per-node defaulting.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast, final

__all__ = ["TreeNode"]


@final
@dataclass(frozen=True, slots=True)
class TreeNode:
    """One node in a tree: a ``label`` and recursively-typed ``children``."""

    label: str
    children: tuple[TreeNode, ...] = ()

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire mapping for this node and subtree."""
        d: dict[str, object] = {"label": self.label}
        if self.children:
            d["children"] = [child.to_dict() for child in self.children]
        return d

    @classmethod
    def decode_all(cls, raw: object, where: str) -> tuple[TreeNode, ...]:
        """Decode a wire node list to typed nodes, raising on the first malformation.

        ``where`` names the position in error messages (e.g. ``nodes`` or
        ``nodes[2].children``) so a deep malformation points the agent at the
        offending node.
        """
        if not isinstance(raw, list):
            msg = f"{where} must be a list of nodes; got {type(raw).__name__}"
            raise ValueError(msg)
        seq = cast("list[object]", raw)
        return tuple(
            cls._decode_one(node, f"{where}[{i}]") for i, node in enumerate(seq)
        )

    @classmethod
    def _decode_one(cls, raw: object, where: str) -> TreeNode:
        """Decode one wire node, recursing into its children."""
        if not isinstance(raw, Mapping):
            msg = f"{where} must be a mapping; got {type(raw).__name__}"
            raise ValueError(msg)
        node = cast("Mapping[str, object]", raw)
        label = node.get("label")
        if not isinstance(label, str):
            msg = f"{where} is missing a string 'label'; got {label!r}"
            raise ValueError(msg)
        children = cls.decode_all(node.get("children", []), f"{where}.children")
        return cls(label=label, children=children)
