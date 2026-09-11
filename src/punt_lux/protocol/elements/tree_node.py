"""TreeNode — a recursive ``label`` + ``id`` + ``children`` value in a ``tree``.

A value family. Malformed nodes raise ``ValueError`` at the wire boundary
(PY-EH-1), before any ``TreeElement`` is constructed. ``to_dict`` is a
``@staticmethod`` (not an instance method) alongside the decode classmethods,
so ``ids()`` stays the sole *instance* method — a public-field dataclass with
two-plus instance methods reads as maximally disjoint to LCOM tooling even
when, as here, they share the same public fields (PY-OO-5's cohesion intent
holds; only the tool's ``self._*``-prefix heuristic misses public fields).
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from itertools import chain
from typing import final

from punt_lux.protocol.elements._util import strip_none
from punt_lux.protocol.elements.wire_require import WireRequire

__all__ = ["TreeNode"]


@final
@dataclass(frozen=True, slots=True)
class TreeNode:
    """One node in a tree: a ``label``, a stable ``id``, and recursive ``children``."""

    label: str
    children: tuple[TreeNode, ...] = ()
    id: str = ""

    def ids(self) -> Iterator[str]:
        """Return this node's own id (if set) and each descendant's, depth-first."""
        return chain(filter(None, (self.id,)), *(c.ids() for c in self.children))

    @staticmethod
    def to_dict(node: TreeNode) -> dict[str, object]:
        """Return ``node``'s JSON-compatible wire mapping, recursing into children."""
        kids = [TreeNode.to_dict(c) for c in node.children] if node.children else None
        d = {"label": node.label, "id": node.id if node.id else None, "children": kids}
        return strip_none(d)

    @classmethod
    def decode_all(cls, raw: object, where: str) -> tuple[TreeNode, ...]:
        """Decode a wire node list, raising with ``where`` naming a bad position."""
        seq = WireRequire.list_(raw, where)
        return tuple(cls._decode_one(n, f"{where}[{i}]") for i, n in enumerate(seq))

    @classmethod
    def _decode_one(cls, raw: object, where: str) -> TreeNode:
        node = WireRequire.mapping(raw, where)
        label = WireRequire.string(
            node.get("label"), f"{where} is missing a string 'label'"
        )
        node_id = WireRequire.string(node.get("id", ""), f"{where}.id must be a string")
        children = cls.decode_all(node.get("children", []), f"{where}.children")
        return cls(label=label, id=node_id, children=children)
