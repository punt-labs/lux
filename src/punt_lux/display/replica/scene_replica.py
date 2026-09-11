"""The Display's replica of the scene graph the Hub sent it."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Self

from punt_lux.display.replica.frame import Frame
from punt_lux.display.replica.frame_book import FrameBook
from punt_lux.display.replica.stale_ids import OnSceneReplacedFn, StaleIds
from punt_lux.display.replica.widget_state import WidgetState, WireScalar
from punt_lux.display.replica.widget_state_store import WidgetStateStore
from punt_lux.domain.identity import HubId, HubScopedKey
from punt_lux.protocol import SceneMessage

__all__ = ["OnSceneReplacedFn", "SceneReplica"]

# handle_framed_scene's own-Hub default -- production dispatch always
# resolves and passes the sender's real HubId; stands in for the many
# existing callers with no real Hub connection in play.
_NO_HUB = HubId.stub()


class SceneReplica:
    """Own the scene graph: framed scenes (via a composed :class:`FrameBook`),
    widget state (:class:`WidgetStateStore`), stale-id bookkeeping
    (:class:`StaleIds`). Two authorities write here: a client owns *content*,
    the user owns *visibility* -- why ``close``/``dispose_frame`` differ."""

    _book: FrameBook
    _widget_state: WidgetStateStore
    _stale: StaleIds

    def __new__(
        cls,
        *,
        on_scene_replaced: OnSceneReplacedFn,
    ) -> Self:
        self = super().__new__(cls)
        self._book = FrameBook()
        self._widget_state = WidgetStateStore()
        self._stale = StaleIds(self._book, on_scene_replaced)
        return self

    @property
    def frames(self) -> Mapping[str, Frame]:
        return self._book.frames

    @property
    def scene_count(self) -> int:
        """Total scenes held across every frame."""
        return sum(len(f.scenes) for f in self._book.frames.values())

    def __len__(self) -> int:
        return len(self._book)

    @property
    def frame_count(self) -> int:
        """Every Hub's own count, never the flattened view a collision
        would undercount."""
        return len(self)

    @property
    def is_empty(self) -> bool:
        return not len(self)

    @property
    def hub_count(self) -> int:
        """The number of distinct Hubs with a frame currently held."""
        return self._book.hub_count()

    @property
    def active_scene_id(self) -> str | None:
        """The first painted frame's active tab -- the display's 'current'
        scene; a docked or closed frame's tab is never it."""
        for frame in self._book.on_screen():
            if frame.active_tab is not None:
                return frame.active_tab
        return None

    @property
    def scene_to_frame(self) -> Mapping[str, str]:
        return self._book.scene_to_frame

    @property
    def scene_to_owner(self) -> Mapping[str, int]:
        return self._book.scene_to_owner

    def request_focus(self, frame_id: str) -> None:
        """Mark ``frame_id`` to take window focus on its next render."""
        self._book.request_focus(frame_id)

    def consume_focus(self, frame_id: str) -> bool:
        """Return whether ``frame_id`` was awaiting focus, clearing the request."""
        return self._book.consume_focus(frame_id)

    def minimize(self, frame_id: str) -> None:
        """Dock the named frame. No-op if it is gone."""
        self._book.minimize(frame_id)

    def raise_frame(self, frame_id: str) -> bool:
        """Restore the named frame and ask for focus; report whether it is
        held -- the gesture behind a user asking for a frame by name."""
        return self._book.restore(frame_id)

    def on_screen_frames(self) -> list[Frame]:
        """Return the frames the renderer paints."""
        return self._book.on_screen()

    def docked_frames(self) -> list[Frame]:
        """Return the frames the dock bar shows a pill for."""
        return self._book.docked()

    def closed_frames(self) -> list[Frame]:
        """Return the frames the user put away."""
        return self._book.closed()

    def reassign_scenes_of(self, departed_fd: int, orphan_fd: int) -> None:
        """Transfer a departed client's framed scenes to a surviving co-owner."""
        self._book.reassign_scenes_of(departed_fd, orphan_fd)

    def scenes_to_purge(
        self, hub: HubId, manifest: frozenset[str], live_hubs: frozenset[HubId]
    ) -> list[tuple[HubScopedKey, str]]:
        """Every ``(frame_key, scene_id)`` pair ``hub``'s manifest disowns --
        ``frame_key`` addresses the owning frame by its OWN Hub, so a purge
        can never resolve a second Hub's same-named frame or scene."""
        return [
            (HubScopedKey(key.hub, frame_id), key.local)
            for key, frame_id in self._book.scene_to_frame_entries()
            if key.local not in manifest
            and (key.hub == hub or key.hub not in live_hubs)
        ]

    def frame(self, frame_id: str, hub: HubId = _NO_HUB) -> Frame | None:
        """The frame ``(hub, frame_id)`` addresses -- collision-safe."""
        return self._book.frame(frame_id, hub)

    def handle_framed_scene(
        self, msg: SceneMessage, owner_fd: int, hub: HubId = _NO_HUB
    ) -> None:
        """Route a scene into its frame, creating the frame if needed. An
        empty push removes the scene instead of keeping a husk frame."""
        key = HubScopedKey(hub, msg.id)
        if not msg.elements:
            self._remove_emptied_scene(key)
            return
        frame = self._book.ensure(msg, owner_fd, hub)
        self._vacate_other_frame(frame, key)
        is_new = msg.id not in frame.scenes
        old_scene = frame.scenes.get(msg.id)
        frame.scenes[msg.id] = msg
        if is_new:
            self._admit_new_scene(frame, key)
        else:
            self._replace_scene_state(key, msg, old_scene)
        self._book.record_owner(key, owner_fd)

    def _remove_emptied_scene(self, key: HubScopedKey) -> None:
        """Drop a scene an empty push named, resolved by its own Hub only --
        no flat fallback, or Hub A's empty push could remove Hub B's scene."""
        stale = self._book.frame_of_hub_scene(key)
        if stale is not None and self.dismiss_framed_scene(stale, key.local):
            self.dispose_frame(stale.frame_id, stale.hub)

    def _vacate_other_frame(self, frame: Frame, key: HubScopedKey) -> None:
        """Take ``key`` out of any other frame owning it, disposing it if that
        empties it -- resolved by ``key``'s own Hub, never another Hub's."""
        old_frame = self._book.frame_of_hub_scene(key)
        if old_frame is None or old_frame.frame_id == frame.frame_id:
            return
        if self.dismiss_framed_scene(old_frame, key.local):
            self.dispose_frame(old_frame.frame_id, old_frame.hub)

    def _admit_new_scene(self, frame: Frame, key: HubScopedKey) -> None:
        """Place a scene the frame did not hold; active tab only for the
        frame's first scene, so a later arrival doesn't move the reader."""
        scene_id = key.local
        frame.scene_order.append(scene_id)
        self._widget_state.open(key)
        if frame.active_tab is None:
            frame.active_tab = scene_id
        self._book.set_frame(key, frame.frame_id)

    def resolve_scene(self, scene_id: str) -> SceneMessage | None:
        """Find a scene in its frame, or None when no frame holds it."""
        frame = self._book.frame_of_scene(scene_id)
        return frame.scenes.get(scene_id) if frame is not None else None

    def dismiss_framed_scene(self, frame: Frame, scene_id: str) -> bool:
        """Remove a scene from ``frame``, return True if now empty -- scoped
        to this exact frame, so another Hub's same-named scene is untouched."""
        dismissed = frame.scenes.pop(scene_id, None)
        if dismissed is not None:
            self._stale.notify(self._stale.in_tree(dismissed.elements))
        frame.scene_order = [s for s in frame.scene_order if s != scene_id]
        self._widget_state.discard(HubScopedKey(frame.hub, scene_id))
        self._book.forget_scene_from(scene_id, frame.frame_id, frame.hub)
        if frame.active_tab == scene_id:
            frame.active_tab = frame.scene_order[0] if frame.scene_order else None
        return not frame.scenes

    def close(self, frame_id: str) -> list[str]:
        """Put a frame away, returning the scene ids to drain -- visibility
        only: content, widget state, and active tab all survive."""
        frame = self._book.close(frame_id)
        if frame is None:
            return []
        return list(frame.scene_order)

    def dispose_frame(self, frame_id: str, hub: HubId = _NO_HUB) -> list[str]:
        """Throw a frame out with all its scenes, returning the stale element
        IDs -- content is gone (empty push, manifest purge, TTL, Clear All)."""
        frame = self._book.pop_frame(frame_id, hub)
        if frame is None:
            return []
        removed_ids = self._stale.of_frame(frame)
        for scene_id in frame.scene_order:
            self._widget_state.discard(HubScopedKey(frame.hub, scene_id))
        self._book.forget_scenes_of_frame(frame_id, frame.hub)
        return self._stale.notify(removed_ids)

    def clear_all(self) -> None:
        """Remove all scenes, frames, and associated state."""
        self._book.clear()
        self._widget_state.clear()

    def dispose_all_frames(self) -> None:
        """Throw out every frame, each by its own owning Hub, notifying
        stale ids per frame -- unlike :meth:`clear_all`'s silent reset."""
        for frame in list(self._book.frames.values()):
            self.dispose_frame(frame.frame_id, frame.hub)

    def frame_ids(self) -> frozenset[str]:
        return frozenset(self._book.frames)

    def hub_ids(self) -> frozenset[HubId]:
        return frozenset(f.hub for f in self._book.frames.values())

    def scene_ids(self) -> frozenset[str]:
        return frozenset(self.scene_to_frame)

    def widget_state_for(
        self, scene_id: str, hub: HubId = _NO_HUB
    ) -> WidgetState | None:
        return self._widget_state.get(HubScopedKey(hub, scene_id))

    def widget_snapshot(
        self, scene_id: str, hub: HubId = _NO_HUB
    ) -> dict[str, WireScalar] | None:
        """The scene's curated widget-state snapshot, or None if untracked."""
        state = self.widget_state_for(scene_id, hub)
        return state.observable_snapshot() if state is not None else None

    def all_widget_snapshots(self) -> dict[str, dict[str, WireScalar]]:
        """Return every tracked scene's curated widget-state snapshot, keyed by id."""
        return self._widget_state.snapshots()

    def frame_presentations(self) -> list[dict[str, object]]:
        """Return every frame's Display-owned facts: visibility, active tab, cascade."""
        return [frame.presentation() for frame in self._book.frames.values()]

    @property
    def widget_state_count(self) -> int:
        """Return the number of scenes holding widget state."""
        return len(self._widget_state)

    # -- scene-replacement helpers -----------------------------------------

    def _replace_scene_state(
        self, key: HubScopedKey, msg: SceneMessage, old_scene: SceneMessage | None
    ) -> None:
        """Drain stale IDs no other scene holds and discard their widget state
        -- survivor-aware, so replacing one scene never cancels another's
        still-valid queued events."""
        if old_scene is None:
            return
        stale_ids = self._stale.dropped_by(msg, old_scene)
        self._stale.notify(stale_ids)
        self._widget_state.retire_elements(key, stale_ids)
