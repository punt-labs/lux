"""Typed exception raised when a connection mutates an element it does not own.

The Hub apply pipeline propagates failures through exceptions; the Display
apply pipeline propagates them through discriminated ``Error`` returns. The
two surfaces share the same vocabulary but the carrier differs.
"""

from __future__ import annotations

from typing import Self

from punt_lux.domain.ids import ConnectionId, ElementId, SceneId

__all__ = ["HubOwnershipError"]


class HubOwnershipError(PermissionError):
    """Raised when a connection mutates an element it does not own."""

    _scene_id: SceneId
    _element_id: ElementId
    _attempting: ConnectionId
    _owning: ConnectionId

    def __new__(
        cls,
        scene_id: SceneId,
        element_id: ElementId,
        attempting: ConnectionId,
        owning: ConnectionId,
    ) -> Self:
        # ``OSError`` reads its first arguments as errno and message, so the real
        # ones are kept as fields and ``__reduce__`` rebuilds from them.
        self = super().__new__(cls)
        self._scene_id = scene_id
        self._element_id = element_id
        self._attempting = attempting
        self._owning = owning
        return self

    def __reduce__(self) -> tuple[object, ...]:
        return (
            type(self),
            (self._scene_id, self._element_id, self._attempting, self._owning),
        )

    @property
    def scene_id(self) -> SceneId:
        """The scene the element is in."""
        return self._scene_id

    @property
    def element_id(self) -> ElementId:
        """The element that was written."""
        return self._element_id

    @property
    def attempting(self) -> ConnectionId:
        """The connection that tried to write it."""
        return self._attempting

    @property
    def owning(self) -> ConnectionId:
        """The connection that owns it."""
        return self._owning

    def __str__(self) -> str:
        return (
            f"connection {self._attempting!r} cannot mutate element "
            f"{self._element_id!r} in scene {self._scene_id!r}: owned by "
            f"{self._owning!r}"
        )
