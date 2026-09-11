"""SceneIndex — the scene→frame and scene→owner placement maps, both keyed by
:class:`HubScopedKey <punt_lux.domain.identity.HubScopedKey>` so two Hubs
minting the identical scene id can never clobber one another.

Composed out of :class:`FrameBook <punt_lux.display.replica.frame_book.FrameBook>`
so FrameBook's own methods cluster around frame storage and this index's own
methods cluster around scene placement, rather than one class touching four
disjoint pieces of state.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.identity import HubId, HubScopedKey, HubScopedStore

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping

__all__ = ["SceneIndex"]


@final
class SceneIndex:
    """Owns the scene→frame and scene→owner placement maps."""

    _scene_to_frame: HubScopedStore[str]
    _scene_to_owner: HubScopedStore[int]
    __slots__ = ("_scene_to_frame", "_scene_to_owner")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._scene_to_frame = HubScopedStore()
        self._scene_to_owner = HubScopedStore()
        return self

    @property
    def scene_to_frame(self) -> Mapping[str, str]:
        """Flat scene id -> frame id view, merged across every Hub."""
        return self._flattened(self._scene_to_frame)

    @property
    def scene_to_owner(self) -> Mapping[str, int]:
        return self._flattened(self._scene_to_owner)

    @staticmethod
    def _flattened[V](store: HubScopedStore[V]) -> MappingProxyType[str, V]:
        return MappingProxyType(store.flatten())

    def frame_id_of(self, key: HubScopedKey) -> str | None:
        """The frame id ``key`` is placed in, resolved by its owning Hub only."""
        return self._scene_to_frame.get(key)

    def entries(self) -> Iterator[tuple[HubScopedKey, str]]:
        """Yield every scene->frame entry with its full Hub-scoped key."""
        return self._scene_to_frame.entries()

    def set_frame(self, key: HubScopedKey, frame_id: str) -> None:
        """Record which Hub-scoped scene now holds ``frame_id``."""
        self._scene_to_frame.put(key, frame_id)

    def record_owner(self, key: HubScopedKey, owner_fd: int) -> None:
        """Record the owning client fd for a Hub-scoped framed scene."""
        self._scene_to_owner.put(key, owner_fd)

    def forget_scene(self, scene_id: str) -> None:
        """Drop a scene's frame and owner mappings, across every Hub."""
        self._scene_to_frame.remove_all(scene_id)
        self._scene_to_owner.remove_all(scene_id)

    def forget_scene_from(self, scene_id: str, frame_id: str, hub: HubId) -> None:
        """Drop exactly the ``(hub, scene_id)`` -> ``frame_id`` mapping --
        resolved by the exact key, never a bare-value search that could
        also match a second Hub's identically-valued entry."""
        key = HubScopedKey(hub, scene_id)
        if self._scene_to_frame.get(key) != frame_id:
            return
        self._scene_to_frame.remove(key)
        self._scene_to_owner.remove(key)

    def forget_scenes_of_frame(self, frame_id: str, hub: HubId) -> None:
        """Drop every ``hub``-owned entry pointing at ``frame_id`` -- the
        whole-frame :meth:`forget_scene_from`, scoped by owner so a second
        Hub's identically-named frame is never a candidate."""
        for key in self._scene_to_frame.remove_matching_hub_value(hub, frame_id):
            self._scene_to_owner.remove(key)

    def reassign_owner(
        self,
        hub: HubId,
        departed_fd: int,
        heir_fd: int,
        scenes: frozenset[str],
    ) -> None:
        """Transfer ``departed_fd``'s ownership of ``scenes`` (one Hub's own)
        to ``heir_fd``."""
        self._scene_to_owner.reassign_value(hub, departed_fd, heir_fd, scenes)

    def clear(self) -> None:
        self._scene_to_frame = HubScopedStore()
        self._scene_to_owner = HubScopedStore()
