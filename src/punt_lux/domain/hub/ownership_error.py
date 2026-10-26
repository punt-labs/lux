"""Typed exception raised when a connection mutates an element it does not own.

The Hub apply pipeline propagates failures through exceptions; the Display
apply pipeline propagates them through discriminated ``Error`` returns. The
two surfaces share the same vocabulary but the carrier differs.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.domain.ids import ConnectionId, ElementId, SceneId

__all__ = ["HubOwnershipError"]


@final
class HubOwnershipError(PermissionError):
    """Raised when a connection mutates an element it does not own."""

    _scene_id: SceneId
    _element_id: ElementId
    _attempting: ConnectionId
    _owning: ConnectionId

    def __new__(cls, *args: object) -> Self:
        match args:
            case (str() as scene_id, str() as element_id, str() as a, str() as o):
                pass
            case _:
                msg = (
                    f"{cls.__name__} takes (scene_id, element_id, attempting, "
                    f"owning), all str, got {args!r}"
                )
                raise TypeError(msg)
        # ``OSError`` reads its first arguments as errno and message, so it is
        # built with none and ``args`` carries the real ones for ``__reduce__``.
        error = super().__new__(cls)
        error.args = args
        error._scene_id = SceneId(scene_id)
        error._element_id = ElementId(element_id)
        error._attempting = ConnectionId(a)
        error._owning = ConnectionId(o)
        return error

    @classmethod
    def of(
        cls,
        scene_id: SceneId,
        element_id: ElementId,
        attempting: ConnectionId,
        owning: ConnectionId,
    ) -> Self:
        """Return the error for ``attempting`` writing what ``owning`` owns."""
        return cls(scene_id, element_id, attempting, owning)

    def __reduce__(self) -> tuple[object, ...]:
        return (type(self), self.args)

    def __repr__(self) -> str:
        return (
            f"{type(self).__name__}({self._scene_id!r}, {self._element_id!r}, "
            f"attempting={self._attempting!r}, owning={self._owning!r})"
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
