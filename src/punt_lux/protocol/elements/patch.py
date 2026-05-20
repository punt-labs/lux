"""Patch element — single-element update payload for UpdateMessage."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "Patch",
    "_patch_from_dict",
    "_patch_to_dict",
]


@dataclass(frozen=True, slots=True)
class Patch:
    """A single element patch within an UpdateMessage."""

    id: str
    set: dict[str, Any] | None = None
    remove: bool = False


def _patch_to_dict(p: Patch) -> dict[str, Any]:
    d: dict[str, Any] = {"id": p.id}
    if p.set is not None:
        d["set"] = p.set
    if p.remove:
        d["remove"] = True
    return d


def _patch_from_dict(d: dict[str, Any]) -> Patch:
    return Patch(
        id=d["id"],
        set=d.get("set"),
        remove=d.get("remove", False),
    )


# Patch codecs are exposed individually rather than via a Serializer table
# because Patch is referenced by UpdateMessage (in protocol/messages.py)
# rather than dispatched through the Element type union.
