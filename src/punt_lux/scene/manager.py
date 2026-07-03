"""Scene graph state machine — SceneManager class and tree helpers."""

from __future__ import annotations

import dataclasses
import logging
from dataclasses import replace
from typing import Any, Self

from punt_lux.domain.element_abc import Element as ABCElement
from punt_lux.protocol import (
    CheckboxElement,
    CollapsingHeaderElement,
    ComboElement,
    Element,
    GroupElement,
    InputNumberElement,
    InputTextElement,
    RadioElement,
    SceneMessage,
    SelectableElement,
    SliderElement,
    TabBarElement,
    UpdateMessage,
    WindowElement,
)
from punt_lux.scene.frame import Frame
from punt_lux.scene.widget_state import WidgetState
from punt_lux.types import OnSceneReplacedFn

# ---------------------------------------------------------------------------
# Recursive element tree helpers
# ---------------------------------------------------------------------------


def _get_children(elem: Element) -> list[list[Any]]:
    """Return all child lists owned by a container element."""
    if isinstance(elem, (GroupElement, CollapsingHeaderElement, WindowElement)):
        result: list[list[Any]] = [elem.children]
        if isinstance(elem, GroupElement) and elem.pages:
            result.extend(elem.pages)
        return result
    if isinstance(elem, TabBarElement):
        return [t.get("children", []) for t in elem.tabs]
    return []


def _collect_ids(elem: Element) -> list[str]:
    """Collect all element IDs in a subtree (including the root)."""
    ids: list[str] = []
    eid = getattr(elem, "id", None)
    if eid is not None:
        ids.append(eid)
    for child_list in _get_children(elem):
        for child in child_list:
            ids.extend(_collect_ids(child))
    return ids


def _find_element(
    elements: list[Element], target_id: str
) -> tuple[list[Element], int] | None:
    """Find element by id, returning (parent_list, index)."""
    for i, e in enumerate(elements):
        if getattr(e, "id", None) == target_id:
            return (elements, i)
        for child_list in _get_children(e):
            result = _find_element(child_list, target_id)
            if result is not None:
                return result
    return None


def _widget_value(elem: Element) -> Any:
    """Extract the current widget value from an element for WidgetState.

    Direct ``isinstance`` dispatch against the seven value-bearing input
    element classes — each owns a ``widget_value()`` method that returns
    the field ``SceneManager`` mirrors into ``WidgetState`` after a patch.
    ``ColorPickerElement`` is intentionally excluded: its renderer seeds
    ``WidgetState`` with an ``ImVec4`` via ``ensure()``, so returning the
    raw hex string here would corrupt that state.
    """
    if isinstance(
        elem,
        (
            CheckboxElement,
            ComboElement,
            InputNumberElement,
            InputTextElement,
            RadioElement,
            SelectableElement,
            SliderElement,
        ),
    ):
        return elem.widget_value()
    return None


# ---------------------------------------------------------------------------
# SceneManager
# ---------------------------------------------------------------------------

_log = logging.getLogger(__name__)


class SceneManager:
    """Own the scene graph — frames, scenes, scene-to-frame mapping,
    widget state per scene, and the update/patch pipeline.

    Pure state machine: no ImGui, no socket, no OpenGL dependency.
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

    def apply_update(self, msg: UpdateMessage) -> None:
        """Apply incremental patches to an existing scene."""
        scene = self.resolve_scene(msg.scene_id)
        if scene is None:
            return
        ws = self._scene_widget_state.get(msg.scene_id)
        for patch in msg.patches:
            result = _find_element(scene.elements, patch.id)
            if result is None:
                continue
            parent_list, idx = result
            if patch.remove:
                removed = parent_list.pop(idx)
                for eid in _collect_ids(removed):
                    if ws is not None:
                        ws.set(eid, None)
                        ws.clear_suffix(f"_{eid}")
            elif patch.set:
                self._apply_patch_set(
                    (parent_list, idx), patch.set, ws, scene_id=msg.scene_id
                )

    def dismiss_scene(self, scene_id: str) -> None:
        """Remove an unframed scene and all its associated state."""
        old_order = self._scene_order
        old_idx = old_order.index(scene_id) if scene_id in old_order else -1
        dismissed = self._scenes.pop(scene_id, None)
        if dismissed is not None:
            dismissed_ids: set[str] = set()
            for elem in dismissed.elements:
                dismissed_ids.update(_collect_ids(elem))
                if isinstance(elem, WindowElement):
                    self._dirty_windows.discard(elem.id)
            # Keep events for IDs that still exist in remaining scenes
            surviving_ids: set[str] = set()
            for scene in self._scenes.values():
                for elem in scene.elements:
                    surviving_ids.update(_collect_ids(elem))
            stale_ids = dismissed_ids - surviving_ids
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
            dismissed_ids: set[str] = set()
            for elem in dismissed.elements:
                dismissed_ids.update(_collect_ids(elem))
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
        """Remove a frame and all its scenes.

        Return the list of stale element IDs removed.  The caller
        (DisplayServer) uses these to drain its event queue and send
        close notifications to clients.
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
                for elem in scene.elements:
                    removed_ids.update(_collect_ids(elem))
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

    # -- replace / patch helpers -------------------------------------------

    def _replace_scene_state(
        self,
        msg: SceneMessage,
        old_scene: SceneMessage | None = None,
    ) -> None:
        """Notify about stale IDs and reset widget state."""
        if old_scene is not None:
            old_ids: set[str] = set()
            for elem in old_scene.elements:
                old_ids.update(_collect_ids(elem))
            new_ids: set[str] = set()
            for elem in msg.elements:
                new_ids.update(_collect_ids(elem))
            stale_ids = old_ids - new_ids
            if stale_ids:
                self._on_scene_replaced(list(stale_ids))
        self._scene_widget_state[msg.id].clear()

    def _apply_patch_set(
        self,
        location: tuple[list[Element], int],
        fields: dict[str, Any],
        ws: WidgetState | None = None,
        *,
        scene_id: str,
    ) -> None:
        """Apply a set-patch to an element and sync widget state.

        Two element shapes coexist: ABC subclasses (currently Text) own
        their patch path via ``_set_<field>`` setters called from
        ``Element.apply_patch``; the remaining dataclasses continue
        through ``dataclasses.replace``. The dispatch branch keeps each
        shape on its native mutation strategy until every kind is an ABC
        subclass.
        """
        parent_list, idx = location
        elem = parent_list[idx]
        if isinstance(elem, ABCElement):
            known = {
                name.removeprefix("_set_")
                for name in dir(elem)
                if name.startswith("_set_") and callable(getattr(elem, name))
            }
        else:
            known = {f.name for f in dataclasses.fields(elem)}
        valid = {
            k: v for k, v in fields.items() if k not in ("id", "kind") and k in known
        }
        unknown = fields.keys() - {"id", "kind"} - valid.keys()
        if unknown:
            element_id = getattr(elem, "id", None)
            msg = (
                f"patch for scene {scene_id!r} element {element_id!r} "
                f"contains unknown fields: {sorted(unknown)}"
            )
            raise ValueError(msg)
        if valid:
            if isinstance(elem, ABCElement):
                elem.apply_patch(valid)
            else:
                parent_list[idx] = elem = replace(elem, **valid)
        eid = getattr(elem, "id", None)
        has_value_key = valid.keys() & {
            "value",
            "selected",
            "items",
        }
        if eid is not None and ws is not None and has_value_key:
            new_value = _widget_value(elem)
            if new_value is None:
                # Element is not one of the value-bearing input kinds
                # (e.g. ColorPickerElement — see ``_widget_value``
                # docstring above for the kept-out list).  Writing None
                # would poison ensure() on the next frame; discarding
                # forces the renderer to re-seed from the patched element
                # fields.
                ws.discard(eid)
            else:
                ws.set(eid, new_value)
        has_pos_key = valid.keys() & {
            "x",
            "y",
            "width",
            "height",
        }
        if eid is not None and isinstance(elem, WindowElement) and has_pos_key:
            self._dirty_windows.add(eid)

    def _next_cascade_index(self) -> int:
        """Return the smallest unused cascade index."""
        used = {f.cascade_index for f in self._frames.values()}
        idx = 0
        while idx in used:
            idx += 1
        return idx
