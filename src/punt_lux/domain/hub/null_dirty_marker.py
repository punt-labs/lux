"""NullDirtyMarker — the connection registry's no-op ``DirtyMarker`` collaborator.

Held before the composition root wires the real replicator in, so
``ClientRegistry`` always has a collaborator to call, never a ``None``.
"""

from __future__ import annotations

from typing import Self, final

__all__ = ["NullDirtyMarker"]


@final
class NullDirtyMarker:
    """No-op marker -- the registry always has a collaborator to call."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def mark_dirty(self, scene_id: str) -> None:
        """Do nothing — no replicator is wired in yet."""

    def mark_menus(self) -> None:
        """Do nothing — no replicator is wired in yet."""

    def __repr__(self) -> str:
        return "NullDirtyMarker()"
