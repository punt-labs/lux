"""TreeNode — a recursive ``label`` + ``id`` + ``children`` value in a ``tree``.

A value family. Malformed nodes raise ``ValueError`` at the wire boundary
(PY-EH-1), before any ``TreeElement`` is constructed.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from itertools import chain
from typing import cast, final

from punt_lux.protocol.elements._util import strip_none

__all__ = ["TreeNode"]


@final
@dataclass(frozen=True, slots=True)
class TreeNode:
    """One node in a tree: a ``label``, a stable ``id``, and recursive ``children``."""

    label: str
    id: str = ""
    children: tuple[TreeNode, ...] = ()

    def ids(self) -> Iterator[str]:
        """Return this node's own id (if set) and each descendant's, depth-first."""
        return chain(filter(None, (self.id,)), *(c.ids() for c in self.children))

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire mapping for this node and subtree."""
        kids = [c.to_dict() for c in self.children] if self.children else None
        d = {"label": self.label, "id": self.id if self.id else None, "children": kids}
        return strip_none(d)

    @classmethod
    def decode_all(cls, raw: object, where: str) -> tuple[TreeNode, ...]:
        """Decode a wire node list, raising with ``where`` naming a bad position."""
        seq = cls._require_list(raw, where)
        return tuple(cls._decode_one(n, f"{where}[{i}]") for i, n in enumerate(seq))

    @classmethod
    def _decode_one(cls, raw: object, where: str) -> TreeNode:
        node = cls._require_mapping(raw, where)
        label = node.get("label")
        if not isinstance(label, str):
            raise ValueError(f"{where} is missing a string 'label'; got {label!r}")
        node_id = node.get("id", "")
        if not isinstance(node_id, str):
            raise ValueError(f"{where}.id must be a string; got {node_id!r}")
        children = cls.decode_all(node.get("children", []), f"{where}.children")
        return cls(label=label, id=node_id, children=children)

    @staticmethod
    def _require_list(raw: object, loc: str) -> list[object]:
        if not isinstance(raw, list):
            raise ValueError(f"{loc} must be a list of nodes; got {type(raw).__name__}")
        return cast("list[object]", raw)

    @staticmethod
    def _require_mapping(raw: object, where: str) -> Mapping[str, object]:
        if not isinstance(raw, Mapping):
            raise ValueError(f"{where} must be a mapping; got {type(raw).__name__}")
        return cast("Mapping[str, object]", raw)
