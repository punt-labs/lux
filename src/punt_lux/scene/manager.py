"""Scene graph state machine — the SceneManager class."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from itertools import chain
from typing import Self

from punt_lux.protocol import (
    LegacyWindowElement,
    SceneMessage,
)
from punt_lux.scene.element_walk import SceneTreeWalk
from punt_lux.scene.frame import Frame
from punt_lux.scene.frame_book import FrameBook
from punt_lux.scene.widget_state import WidgetState
from punt_lux.types import OnSceneReplacedFn

_log = logging.getLogger(__name__)


class SceneManager:
    """Own the scene graph — unframed scenes, widget state, stale-id notification.

    Frames and the scene→frame/owner maps belong to a composed :class:`FrameBook`;
    this class keeps the unframed scenes, per-scene widget state, and the stale-id
    notification the two share. Pure state machine: no ImGui, socket, or OpenGL.
    Tree navigation is delegated to :class:`SceneTreeWalk`.
    """

    _scenes: dict[str, SceneMessage]
    _scene_order: list[str]
    _active_tab: str | None
    _book: FrameBook
    _scene_widget_state: dict[str, WidgetState]
    _dirty_windows: set[str]
    _on_scene_replaced: OnSceneReplacedFn
    _walk: SceneTreeWalk

    def __new__(
        cls,
        *,
        on_scene_replaced: OnSceneReplacedFn,
    ) -> Self:
        self = super().__new__(cls)
        self._scenes = {}
        self._scene_order = []
        self._active_tab = None
        self._book = FrameBook()
        self._scene_widget_state = {}
        self._dirty_windows = set()
        self._on_scene_replaced = on_scene_replaced
        self._walk = SceneTreeWalk()
        return self

    # -- read-only access for the rendering layer ---------------------------

    @property
    def scenes(self) -> dict[str, SceneMessage]:
        return self._scenes

    @property
    def scene_order(self) -> list[str]:
        return self._scene_order

    @property
    def active_tab(self) -> str | None:
        return self._active_tab

    @active_tab.setter
    def active_tab(self, value: str | None) -> None:
        self._active_tab = value

    @property
    def frames(self) -> Mapping[str, Frame]:
        return self._book.frames

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

    @property
    def dirty_windows(self) -> set[str]:
        return self._dirty_windows

    # -- public API --------------------------------------------------------

    def handle_scene(self, msg: SceneMessage) -> None:
        """Add or replace an unframed scene; an empty push dismisses it.

        The Hub blanks a removed scene by pushing it with no elements, so an
        empty push is a removal — the scene disappears rather than lingering as
        an empty husk.
        """
        if not msg.elements:
            self.dismiss_scene(msg.id)
            return
        is_new = msg.id not in self._scenes
        old_scene = self._scenes.get(msg.id)
        self._scenes[msg.id] = msg
        if is_new:
            self._scene_order.append(msg.id)
            self._scene_widget_state[msg.id] = WidgetState()
            self._active_tab = msg.id
            for elem in msg.elements:
                if isinstance(elem, LegacyWindowElement):
                    self._dirty_windows.add(elem.id)
        else:
            self._replace_scene_state(msg, old_scene)

    def handle_framed_scene(self, msg: SceneMessage, owner_fd: int) -> None:
        """Route a scene into a frame, creating the frame if needed.

        An empty push removes the scene from its frame instead of creating or
        keeping one: the frame and its content appear and disappear together, so
        an emptied scene never lingers as a husk frame.
        """
        frame_id = msg.frame_id
        if frame_id is None:
            return
        if not msg.elements:
            # An emptied scene push is the Hub signalling removal: dismiss it from
            # whatever frame holds it and close the frame once it holds nothing,
            # so no husk frame lingers. An untracked scene is a no-op.
            stale = self._book.frame_of_scene(msg.id) or self._book.frames.get(frame_id)
            if stale is not None and self.dismiss_framed_scene(stale, msg.id):
                self.close_frame(stale.frame_id)
            return
        frame = self._book.ensure(msg, frame_id, owner_fd)
        self.upsert_scene_in_frame(frame, msg)
        self._book.record_owner(msg.id, owner_fd)
        frame.minimized = False
        self._book.request_focus(frame_id)

    def upsert_scene_in_frame(self, frame: Frame, msg: SceneMessage) -> None:
        """Add or replace a scene within a frame."""
        # If this scene_id exists elsewhere, remove it from the old
        # location to prevent the same scene rendering in two places.
        old_frame_id = self._book.scene_to_frame.get(msg.id)
        if old_frame_id is not None and old_frame_id != frame.frame_id:
            old_frame = self._book.frames.get(old_frame_id)
            if old_frame is not None and self.dismiss_framed_scene(old_frame, msg.id):
                self.close_frame(old_frame.frame_id)
        elif msg.id in self._scenes:
            self.dismiss_scene(msg.id)
        is_new = msg.id not in frame.scenes
        old_scene = frame.scenes.get(msg.id)
        frame.scenes[msg.id] = msg
        if is_new:
            frame.scene_order.append(msg.id)
            self._scene_widget_state[msg.id] = WidgetState()
            frame.active_tab = msg.id
            self._book.set_frame(msg.id, frame.frame_id)
            for elem in msg.elements:
                if isinstance(elem, LegacyWindowElement):
                    self._dirty_windows.add(elem.id)
        else:
            self._replace_scene_state(msg, old_scene)

    def resolve_scene(self, scene_id: str) -> SceneMessage | None:
        """Find a scene in either unframed or framed storage."""
        scene = self._scenes.get(scene_id)
        if scene is not None:
            return scene
        frame = self._book.frame_of_scene(scene_id)
        return frame.scenes.get(scene_id) if frame is not None else None

    def dismiss_scene(self, scene_id: str) -> None:
        """Remove an unframed scene and all its associated state."""
        old_order = self._scene_order
        old_idx = old_order.index(scene_id) if scene_id in old_order else -1
        dismissed = self._scenes.pop(scene_id, None)
        if dismissed is not None:
            for elem in dismissed.elements:
                if isinstance(elem, LegacyWindowElement):
                    self._dirty_windows.discard(elem.id)
            self._notify_stale(self._element_ids(dismissed.elements))
        self._scene_order = [s for s in old_order if s != scene_id]
        self._scene_widget_state.pop(scene_id, None)
        if self._active_tab == scene_id:
            new_idx = min(old_idx, len(self._scene_order) - 1)
            self._active_tab = self._scene_order[new_idx] if self._scene_order else None

    def dismiss_framed_scene(
        self,
        frame: Frame,
        scene_id: str,
    ) -> bool:
        """Remove a single scene from a frame.

        Return True if the frame is now empty (caller should close it
        with notifications).
        """
        dismissed = frame.scenes.pop(scene_id, None)
        if dismissed is not None:
            self._notify_stale(self._element_ids(dismissed.elements))
        frame.scene_order = [s for s in frame.scene_order if s != scene_id]
        self._scene_widget_state.pop(scene_id, None)
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
            self._scene_widget_state.pop(scene_id, None)
            self._book.forget_scene(scene_id)
        return self._notify_stale(removed_ids)

    def clear_all(self) -> None:
        """Remove all scenes, frames, and associated state."""
        self._scenes.clear()
        self._scene_order.clear()
        self._active_tab = None
        self._book.clear()
        self._scene_widget_state.clear()
        self._dirty_windows.clear()

    def widget_state_for(self, scene_id: str) -> WidgetState | None:
        """Return the WidgetState for a scene, or None."""
        return self._scene_widget_state.get(scene_id)

    # -- scene-replacement helpers -----------------------------------------

    def _notify_stale(self, candidate_ids: set[str]) -> list[str]:
        """Report and return candidate ids no surviving framed/unframed scene holds."""
        stale = candidate_ids - self._surviving_element_ids()
        if stale:
            self._on_scene_replaced(list(stale))
        return list(stale)

    def _surviving_element_ids(self) -> set[str]:
        """Return every element id held by any stored scene, framed or not."""
        ids: set[str] = set()
        for scene in chain(self._scenes.values(), self._book.framed_scenes()):
            ids |= self._element_ids(scene.elements)
        return ids

    def _replace_scene_state(
        self,
        msg: SceneMessage,
        old_scene: SceneMessage | None = None,
    ) -> None:
        """Drain stale IDs no other scene holds and discard their widget state.

        A whole-root re-push must not wipe survivors' id-keyed state (selection,
        scroll, in-progress text) — only the departed elements' state is discarded.
        The event drain is survivor-aware: an id this scene dropped is drained only
        when no other framed or unframed scene holds it, so replacing one scene
        never cancels another's still-valid queued events. Echo-suppression resets
        every honoured key so a surviving tab bar re-honours the Hub active tab
        rather than firing a spurious ``TabChanged`` off a stale value.
        """
        if old_scene is None:
            return
        old_ids = self._element_ids(old_scene.elements)
        stale_ids = old_ids - self._element_ids(msg.elements)
        self._notify_stale(stale_ids)
        widget_state = self._scene_widget_state.get(msg.id)
        if widget_state is not None:
            for stale_id in stale_ids:
                widget_state.discard_for(stale_id)
            widget_state.reset_honoured()

    def _element_ids(self, elements: Sequence[object]) -> set[str]:
        """Return every element id in ``elements``, recursing containers."""
        ids: set[str] = set()
        for elem in elements:
            ids.update(self._walk.collect_ids(elem))
        return ids
