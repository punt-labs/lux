"""Scene graph state machine — the SceneManager class."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Self

from punt_lux.protocol import (
    SceneMessage,
    WindowElement,
)
from punt_lux.scene.element_walk import SceneTreeWalk
from punt_lux.scene.frame import Frame
from punt_lux.scene.widget_state import WidgetState
from punt_lux.types import OnSceneReplacedFn

_log = logging.getLogger(__name__)


class SceneManager:
    """Own the scene graph — frames, scenes, scene-to-frame mapping, widget state.

    Pure state machine: no ImGui, socket, or OpenGL. Tree navigation is delegated
    to :class:`SceneTreeWalk`.
    """

    _scenes: dict[str, SceneMessage]
    _scene_order: list[str]
    _active_tab: str | None
    _frames: dict[str, Frame]
    _focus_frame_id: str | None
    _scene_to_frame: dict[str, str]
    _scene_to_owner: dict[str, int]
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
        self._frames = {}
        self._focus_frame_id = None
        self._scene_to_frame = {}
        self._scene_to_owner = {}
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
    def frames(self) -> dict[str, Frame]:
        return self._frames

    @property
    def focus_frame_id(self) -> str | None:
        return self._focus_frame_id

    @focus_frame_id.setter
    def focus_frame_id(self, value: str | None) -> None:
        self._focus_frame_id = value

    @property
    def scene_to_frame(self) -> dict[str, str]:
        return self._scene_to_frame

    @property
    def scene_to_owner(self) -> dict[str, int]:
        return self._scene_to_owner

    @property
    def dirty_windows(self) -> set[str]:
        return self._dirty_windows

    # -- public API --------------------------------------------------------

    def handle_scene(
        self,
        msg: SceneMessage,
        owner_fd: int,  # noqa: ARG002
    ) -> None:
        """Add or replace an unframed scene."""
        is_new = msg.id not in self._scenes
        old_scene = self._scenes.get(msg.id)
        self._scenes[msg.id] = msg
        if is_new:
            self._scene_order.append(msg.id)
            self._scene_widget_state[msg.id] = WidgetState()
            self._active_tab = msg.id
            for elem in msg.elements:
                if isinstance(elem, WindowElement):
                    self._dirty_windows.add(elem.id)
        else:
            self._replace_scene_state(msg, old_scene)

    def handle_framed_scene(self, msg: SceneMessage, owner_fd: int) -> None:
        """Route a scene into a frame, creating the frame if needed."""
        frame_id = msg.frame_id
        if frame_id is None:
            return
        frame = self._frames.get(frame_id)
        if frame is None:
            title = msg.frame_title or msg.title or frame_id
            frame = Frame(
                frame_id=frame_id,
                title=title,
                owner_fds={owner_fd},
                scenes={},
                scene_order=[],
                cascade_index=self._next_cascade_index(),
                initial_size=msg.frame_size,
                flags=msg.frame_flags,
                layout=msg.frame_layout or "tab",
            )
            self._frames[frame_id] = frame
        else:
            frame.owner_fds.add(owner_fd)
        self.upsert_scene_in_frame(frame, msg)
        self._scene_to_owner[msg.id] = owner_fd
        if msg.frame_title:
            frame.title = msg.frame_title
        if msg.frame_flags is not None:
            frame.flags = msg.frame_flags
        if msg.frame_layout is not None:
            frame.layout = msg.frame_layout
        frame.minimized = False
        self._focus_frame_id = frame_id

    def upsert_scene_in_frame(self, frame: Frame, msg: SceneMessage) -> None:
        """Add or replace a scene within a frame."""
        # If this scene_id exists elsewhere, remove it from the old
        # location to prevent the same scene rendering in two places.
        old_frame_id = self._scene_to_frame.get(msg.id)
        if old_frame_id is not None and old_frame_id != frame.frame_id:
            old_frame = self._frames.get(old_frame_id)
            if old_frame is not None:
                frame_empty = self.dismiss_framed_scene(old_frame, msg.id)
                if frame_empty:
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
            self._scene_to_frame[msg.id] = frame.frame_id
            for elem in msg.elements:
                if isinstance(elem, WindowElement):
                    self._dirty_windows.add(elem.id)
        else:
            self._replace_scene_state(msg, old_scene)

    def resolve_scene(self, scene_id: str) -> SceneMessage | None:
        """Find a scene in either unframed or framed storage."""
        scene = self._scenes.get(scene_id)
        if scene is not None:
            return scene
        frame_id = self._scene_to_frame.get(scene_id)
        if frame_id is not None:
            frame = self._frames.get(frame_id)
            if frame is not None:
                return frame.scenes.get(scene_id)
        return None

    def dismiss_scene(self, scene_id: str) -> None:
        """Remove an unframed scene and all its associated state."""
        old_order = self._scene_order
        old_idx = old_order.index(scene_id) if scene_id in old_order else -1
        dismissed = self._scenes.pop(scene_id, None)
        if dismissed is not None:
            for elem in dismissed.elements:
                if isinstance(elem, WindowElement):
                    self._dirty_windows.discard(elem.id)
            surviving_ids: set[str] = set()
            for scene in self._scenes.values():  # keep IDs still present elsewhere
                surviving_ids |= self._element_ids(scene.elements)
            stale_ids = self._element_ids(dismissed.elements) - surviving_ids
            if stale_ids:
                self._on_scene_replaced(list(stale_ids))
        self._scene_order = [s for s in old_order if s != scene_id]
        self._scene_widget_state.pop(scene_id, None)
        if self._active_tab == scene_id:
            if self._scene_order:
                new_idx = min(old_idx, len(self._scene_order) - 1)
                self._active_tab = self._scene_order[new_idx]
            else:
                self._active_tab = None

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
            dismissed_ids = self._element_ids(dismissed.elements)
            if dismissed_ids:
                self._on_scene_replaced(list(dismissed_ids))
        frame.scene_order = [s for s in frame.scene_order if s != scene_id]
        self._scene_widget_state.pop(scene_id, None)
        self._scene_to_frame.pop(scene_id, None)
        self._scene_to_owner.pop(scene_id, None)
        if frame.active_tab == scene_id:
            frame.active_tab = frame.scene_order[0] if frame.scene_order else None
        return not frame.scenes

    def close_frame(self, frame_id: str) -> list[str]:
        """Remove a frame and all its scenes, returning the stale element IDs.

        The caller drains its event queue and sends close notifications from them.
        """
        frame = self._frames.pop(frame_id, None)
        if frame is None:
            return []
        if self._focus_frame_id == frame_id:
            self._focus_frame_id = None
        removed_ids: set[str] = set()
        for scene_id in frame.scene_order:
            scene = frame.scenes.get(scene_id)
            if scene is not None:
                removed_ids |= self._element_ids(scene.elements)
            self._scene_widget_state.pop(scene_id, None)
            self._scene_to_frame.pop(scene_id, None)
            self._scene_to_owner.pop(scene_id, None)
        stale = list(removed_ids)
        if stale:
            self._on_scene_replaced(stale)
        return stale

    def clear_all(self) -> None:
        """Remove all scenes, frames, and associated state."""
        self._scenes.clear()
        self._scene_order.clear()
        self._active_tab = None
        self._frames.clear()
        self._scene_to_frame.clear()
        self._scene_to_owner.clear()
        self._scene_widget_state.clear()
        self._dirty_windows.clear()

    def widget_state_for(self, scene_id: str) -> WidgetState | None:
        """Return the WidgetState for a scene, or None."""
        return self._scene_widget_state.get(scene_id)

    # -- scene-replacement helpers -----------------------------------------

    def _replace_scene_state(
        self,
        msg: SceneMessage,
        old_scene: SceneMessage | None = None,
    ) -> None:
        """Notify about stale IDs and discard only their transient widget state.

        A whole-root re-push must not wipe survivors' id-keyed state (selection,
        scroll, in-progress text) — only the departed elements' state is discarded.
        """
        if old_scene is None:
            return
        stale_ids = self._element_ids(old_scene.elements) - self._element_ids(
            msg.elements
        )
        if stale_ids:
            self._on_scene_replaced(list(stale_ids))
        widget_state = self._scene_widget_state.get(msg.id)
        if widget_state is not None:
            for stale_id in stale_ids:
                widget_state.discard_for(stale_id)

    def _element_ids(self, elements: Sequence[object]) -> set[str]:
        """Return every element id in ``elements``, recursing containers."""
        ids: set[str] = set()
        for elem in elements:
            ids.update(self._walk.collect_ids(elem))
        return ids

    def _next_cascade_index(self) -> int:
        """Return the smallest unused cascade index."""
        used = {f.cascade_index for f in self._frames.values()}
        idx = 0
        while idx in used:
            idx += 1
        return idx
