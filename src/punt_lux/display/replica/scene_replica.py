"""The Display's replica of the scene graph the Hub sent it."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Self

from punt_lux.display.replica.element_walk import SceneTreeWalk
from punt_lux.display.replica.frame import Frame
from punt_lux.display.replica.frame_book import FrameBook
from punt_lux.display.replica.widget_state import WidgetState
from punt_lux.display.replica.widget_state_store import WidgetStateStore
from punt_lux.protocol import SceneMessage

type OnSceneReplacedFn = Callable[[list[str]], None]


class SceneReplica:
    """Own the scene graph — framed scenes, widget state, stale-id notification.

    Every scene lives in a frame: the Hub synthesizes one at the render boundary
    when the caller names none, so there is no unframed scene storage. Frames and
    the scene→frame/owner maps belong to a composed :class:`FrameBook`, and the
    per-scene widget state to a composed :class:`WidgetStateStore`; this class
    keeps the stale-id notification the frames share. Pure state machine: no
    ImGui, socket, or OpenGL. Tree navigation is delegated to
    :class:`SceneTreeWalk`.
    """

    _book: FrameBook
    _widget_state: WidgetStateStore
    _on_scene_replaced: OnSceneReplacedFn
    _walk: SceneTreeWalk

    def __new__(
        cls,
        *,
        on_scene_replaced: OnSceneReplacedFn,
    ) -> Self:
        self = super().__new__(cls)
        self._book = FrameBook()
        self._widget_state = WidgetStateStore()
        self._on_scene_replaced = on_scene_replaced
        self._walk = SceneTreeWalk()
        return self

    # -- read-only access for the rendering layer ---------------------------

    @property
    def frames(self) -> Mapping[str, Frame]:
        return self._book.frames

    @property
    def scene_count(self) -> int:
        """Total scenes held across every frame."""
        return sum(len(f.scenes) for f in self._book.frames.values())

    @property
    def frame_count(self) -> int:
        """Number of open frames."""
        return len(self._book.frames)

    @property
    def active_scene_id(self) -> str | None:
        """The first frame's active tab — the display's single 'current' scene."""
        for frame in self._book.frames.values():
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
        """Minimize the named frame. No-op if it is gone."""
        self._book.minimize(frame_id)

    def reassign_scenes_of(self, departed_fd: int, orphan_fd: int) -> None:
        """Transfer a departed client's framed scenes to a surviving co-owner."""
        self._book.reassign_scenes_of(departed_fd, orphan_fd)

    # -- public API --------------------------------------------------------

    def handle_framed_scene(self, msg: SceneMessage, owner_fd: int) -> None:
        """Route a scene into its frame, creating the frame if needed.

        An empty push removes the scene instead of creating or keeping a frame:
        the frame and its content appear and disappear together, never as a husk.
        """
        frame_id = msg.frame_id
        if not msg.elements:
            stale = self._book.frame_of_scene(msg.id) or self._book.frames.get(frame_id)
            if stale is not None and self.dismiss_framed_scene(stale, msg.id):
                self.close_frame(stale.frame_id)
            return
        frame = self._book.ensure(msg, frame_id, owner_fd)
        self.upsert_scene_in_frame(frame, msg)
        self._book.record_owner(msg.id, owner_fd)

    def upsert_scene_in_frame(self, frame: Frame, msg: SceneMessage) -> None:
        """Add or replace a scene within a frame.

        A scene new to the frame earns its attention — tab, raise, focus; a
        replacement repaints in place and earns none of it.
        """
        # A scene lives in one frame at a time: dismiss it from any other.
        old_frame = self._book.frame_of_scene(msg.id)
        if (
            old_frame is not None
            and old_frame.frame_id != frame.frame_id
            and self.dismiss_framed_scene(old_frame, msg.id)
        ):
            self.close_frame(old_frame.frame_id)
        is_new = msg.id not in frame.scenes
        old_scene = frame.scenes.get(msg.id)
        frame.scenes[msg.id] = msg
        if is_new:
            frame.scene_order.append(msg.id)
            self._widget_state.open(msg.id)
            frame.active_tab = msg.id
            frame.minimized = False
            self._book.set_frame(msg.id, frame.frame_id)
            self._book.request_focus(frame.frame_id)
        else:
            self._replace_scene_state(msg, old_scene)

    def resolve_scene(self, scene_id: str) -> SceneMessage | None:
        """Find a scene in its frame, or None when no frame holds it."""
        frame = self._book.frame_of_scene(scene_id)
        return frame.scenes.get(scene_id) if frame is not None else None

    def dismiss_framed_scene(self, frame: Frame, scene_id: str) -> bool:
        """Remove a single scene from a frame.

        Return True if the frame is now empty (caller should close it
        with notifications).
        """
        dismissed = frame.scenes.pop(scene_id, None)
        if dismissed is not None:
            self._notify_stale(self._element_ids(dismissed.elements))
        frame.scene_order = [s for s in frame.scene_order if s != scene_id]
        self._widget_state.discard(scene_id)
        self._book.forget_scene(scene_id)
        if frame.active_tab == scene_id:
            frame.active_tab = frame.scene_order[0] if frame.scene_order else None
        return not frame.scenes

    def close_frame(self, frame_id: str) -> list[str]:
        """Remove a frame and all its scenes, returning the stale element IDs.

        The caller drains its event queue and sends close notifications from them.
        """
        frame = self._book.pop_frame(frame_id)
        if frame is None:
            return []
        removed_ids: set[str] = set()
        for scene_id in frame.scene_order:
            scene = frame.scenes.get(scene_id)
            if scene is not None:
                removed_ids |= self._element_ids(scene.elements)
            self._widget_state.discard(scene_id)
            self._book.forget_scene(scene_id)
        return self._notify_stale(removed_ids)

    def clear_all(self) -> None:
        """Remove all scenes, frames, and associated state."""
        self._book.clear()
        self._widget_state.clear()

    def widget_state_for(self, scene_id: str) -> WidgetState | None:
        """Return the WidgetState for a scene, or None."""
        return self._widget_state.get(scene_id)

    @property
    def widget_state_count(self) -> int:
        """Return the number of scenes holding widget state."""
        return len(self._widget_state)

    # -- scene-replacement helpers -----------------------------------------

    def _notify_stale(self, candidate_ids: set[str]) -> list[str]:
        """Report and return candidate ids no surviving framed scene holds."""
        stale = candidate_ids - self._surviving_element_ids()
        if stale:
            self._on_scene_replaced(list(stale))
        return list(stale)

    def _surviving_element_ids(self) -> set[str]:
        """Return every element id held by any framed scene still stored."""
        ids: set[str] = set()
        for scene in self._book.framed_scenes():
            ids |= self._element_ids(scene.elements)
        return ids

    def _replace_scene_state(
        self, msg: SceneMessage, old_scene: SceneMessage | None = None
    ) -> None:
        """Drain stale IDs no other scene holds and discard their widget state.

        The event drain is survivor-aware: an id this scene dropped is drained only
        when no other framed scene holds it, so replacing one scene never cancels
        another's still-valid queued events.
        """
        if old_scene is None:
            return
        old_ids = self._element_ids(old_scene.elements)
        stale_ids = old_ids - self._element_ids(msg.elements)
        self._notify_stale(stale_ids)
        self._widget_state.retire_elements(msg.id, stale_ids)

    def _element_ids(self, elements: Sequence[object]) -> set[str]:
        """Return every element id in ``elements``, recursing containers."""
        ids: set[str] = set()
        for elem in elements:
            ids.update(self._walk.collect_ids(elem))
        return ids
