"""Characterization tests for SceneManager extraction from DisplayServer.

These tests verify scene management behavior: adding scenes, replacing them,
framing, dismissing, updating, and clearing.  They test SceneManager directly
as a pure state machine — no ImGui, no sockets, no DisplayServer.
"""

from __future__ import annotations

from punt_lux.protocol import (
    ButtonElement,
    SceneMessage,
    SeparatorElement,
    TextElement,
    WindowElement,
)
from punt_lux.scene import SceneManager, WidgetState


def _make_scene(
    scene_id: str = "s1",
    *,
    frame_id: str | None = None,
    frame_title: str | None = None,
    frame_size: tuple[int, int] | None = None,
    frame_flags: dict[str, bool] | None = None,
    frame_layout: str | None = None,
    elements: list[object] | None = None,
    title: str | None = None,
) -> SceneMessage:
    """Build a SceneMessage with sensible defaults."""
    if elements is None:
        elements = [
            TextElement(id="t1", content="Hello", style="heading"),
            ButtonElement(id="b1", label="Click"),
            SeparatorElement(),
        ]
    return SceneMessage(
        id=scene_id,
        elements=elements,  # type: ignore[arg-type]
        frame_id=frame_id,
        frame_title=frame_title,
        frame_size=frame_size,
        frame_flags=frame_flags,
        frame_layout=frame_layout,  # type: ignore[arg-type]
        title=title,
    )


def _make_manager() -> tuple[SceneManager, list[list[str]]]:
    """Create a SceneManager with captured stale-id callbacks.

    Returns (manager, stale_calls) where stale_calls collects every
    call to the on_scene_replaced callback.
    """
    stale_calls: list[list[str]] = []

    def on_replaced(stale_ids: list[str]) -> None:
        stale_calls.append(stale_ids)

    mgr = SceneManager(on_scene_replaced=on_replaced)
    return mgr, stale_calls


# -------------------------------------------------------------------
# 1. test_handle_scene_new
# -------------------------------------------------------------------


class TestHandleSceneNew:
    def test_scene_appears_in_state(self) -> None:
        """A new scene populates scenes, order, active_tab, and widget state."""
        mgr, _ = _make_manager()
        scene = _make_scene()

        mgr.handle_scene(scene, owner_fd=10)

        assert "s1" in mgr._scenes
        assert mgr._scene_order == ["s1"]
        assert mgr._active_tab == "s1"
        assert isinstance(mgr._scene_widget_state.get("s1"), WidgetState)

    def test_window_elements_marked_dirty(self) -> None:
        """Window elements in a new scene are added to _dirty_windows."""
        mgr, _ = _make_manager()
        scene = _make_scene(elements=[WindowElement(id="w1", children=[], title="Win")])

        mgr.handle_scene(scene, owner_fd=10)

        assert "w1" in mgr._dirty_windows


# -------------------------------------------------------------------
# 2. test_handle_scene_replace
# -------------------------------------------------------------------


class TestHandleSceneReplace:
    def test_replacement_overwrites_scene(self) -> None:
        """Sending a scene with the same id replaces the previous one."""
        mgr, stale_calls = _make_manager()
        first = _make_scene(elements=[TextElement(id="t1", content="First")])
        second = _make_scene(elements=[TextElement(id="t2", content="Second")])

        mgr.handle_scene(first, owner_fd=10)
        mgr.handle_scene(second, owner_fd=10)

        assert mgr._scenes["s1"].elements[0].id == "t2"
        assert mgr._scene_order == ["s1"]
        # on_scene_replaced called with stale IDs (t1 removed, t2 added)
        assert len(stale_calls) == 1
        assert "t1" in stale_calls[0]

    def test_widget_state_cleared_on_replace(self) -> None:
        """Widget state is cleared when a scene is replaced."""
        mgr, _ = _make_manager()
        scene = _make_scene()
        mgr.handle_scene(scene, owner_fd=10)

        # Seed widget state
        mgr._scene_widget_state["s1"].set("t1", "stale_value")

        replacement = _make_scene(elements=[TextElement(id="t1", content="New")])
        mgr.handle_scene(replacement, owner_fd=10)

        assert mgr._scene_widget_state["s1"].get("t1") is None


# -------------------------------------------------------------------
# 3. test_handle_framed_scene
# -------------------------------------------------------------------


class TestHandleFramedScene:
    def test_frame_created_with_scene(self) -> None:
        """A SceneMessage with frame_id creates a Frame containing the scene."""
        mgr, _ = _make_manager()
        scene = _make_scene(frame_id="f1", frame_title="My Frame")

        mgr.handle_framed_scene(scene, owner_fd=10)

        assert "f1" in mgr._frames
        frame = mgr._frames["f1"]
        assert frame.title == "My Frame"
        assert "s1" in frame.scenes
        assert frame.scene_order == ["s1"]
        assert mgr._scene_to_frame["s1"] == "f1"
        assert mgr._scene_to_owner["s1"] == 10
        assert mgr._focus_frame_id == "f1"

    def test_second_scene_joins_frame(self) -> None:
        """A second scene with the same frame_id is added to the frame."""
        mgr, _ = _make_manager()
        s1 = _make_scene(scene_id="s1", frame_id="f1", frame_title="Frame")
        s2 = _make_scene(scene_id="s2", frame_id="f1")

        mgr.handle_framed_scene(s1, owner_fd=10)
        mgr.handle_framed_scene(s2, owner_fd=11)

        frame = mgr._frames["f1"]
        assert set(frame.scenes.keys()) == {"s1", "s2"}
        assert frame.scene_order == ["s1", "s2"]
        assert frame.owner_fds == {10, 11}


# -------------------------------------------------------------------
# 4. test_dismiss_scene
# -------------------------------------------------------------------


class TestDismissScene:
    def test_cleanup_and_neighbor_selection(self) -> None:
        """Dismissing a scene removes state and selects the neighbor tab."""
        mgr, _ = _make_manager()
        s1 = _make_scene(scene_id="s1")
        s2 = _make_scene(scene_id="s2")
        s3 = _make_scene(scene_id="s3")

        mgr.handle_scene(s1, owner_fd=10)
        mgr.handle_scene(s2, owner_fd=10)
        mgr.handle_scene(s3, owner_fd=10)
        mgr._active_tab = "s2"

        mgr.dismiss_scene("s2")

        assert "s2" not in mgr._scenes
        assert "s2" not in mgr._scene_order
        assert "s2" not in mgr._scene_widget_state
        # s2 was at index 1 — next neighbor is s3 (min(1, 1) = index 1)
        assert mgr._active_tab == "s3"

    def test_dismiss_last_scene(self) -> None:
        """Dismissing the only scene sets _active_tab to None."""
        mgr, _ = _make_manager()
        mgr.handle_scene(_make_scene(), owner_fd=10)

        mgr.dismiss_scene("s1")

        assert mgr._active_tab is None
        assert len(mgr._scenes) == 0

    def test_dismiss_removes_window_dirty_flags(self) -> None:
        """WindowElement dirty flags are cleaned when the scene is dismissed."""
        mgr, _ = _make_manager()
        scene = _make_scene(elements=[WindowElement(id="w1", children=[], title="Win")])
        mgr.handle_scene(scene, owner_fd=10)
        assert "w1" in mgr._dirty_windows

        mgr.dismiss_scene("s1")

        assert "w1" not in mgr._dirty_windows


# -------------------------------------------------------------------
# 5. test_close_frame
# -------------------------------------------------------------------


class TestCloseFrame:
    def test_frame_and_scene_state_cleaned(self) -> None:
        """Closing a frame removes the frame and all its scenes."""
        mgr, _ = _make_manager()
        s1 = _make_scene(scene_id="s1", frame_id="f1", frame_title="Frame")
        s2 = _make_scene(scene_id="s2", frame_id="f1")

        mgr.handle_framed_scene(s1, owner_fd=10)
        mgr.handle_framed_scene(s2, owner_fd=10)

        stale_ids = mgr.close_frame("f1")

        assert "f1" not in mgr._frames
        assert "s1" not in mgr._scene_to_frame
        assert "s2" not in mgr._scene_to_frame
        assert "s1" not in mgr._scene_widget_state
        assert "s2" not in mgr._scene_widget_state
        assert "s1" not in mgr._scene_to_owner
        assert "s2" not in mgr._scene_to_owner
        # stale_ids should include element ids from the dismissed scenes
        assert len(stale_ids) > 0

    def test_close_nonexistent_frame(self) -> None:
        """Closing a frame that doesn't exist returns empty stale list."""
        mgr, _ = _make_manager()
        stale_ids = mgr.close_frame("no-such-frame")
        assert stale_ids == []

    def test_focus_frame_cleared(self) -> None:
        """If the closed frame was focused, _focus_frame_id is cleared."""
        mgr, _ = _make_manager()
        s1 = _make_scene(scene_id="s1", frame_id="f1", frame_title="Frame")
        mgr.handle_framed_scene(s1, owner_fd=10)
        assert mgr._focus_frame_id == "f1"

        mgr.close_frame("f1")

        assert mgr._focus_frame_id is None


# -------------------------------------------------------------------
# 7. test_upsert_scene_dedup
# -------------------------------------------------------------------


class TestUpsertSceneDedup:
    def test_scene_moves_between_frames(self) -> None:
        """Sending the same scene to a second frame removes it from the first."""
        mgr, _ = _make_manager()
        s1 = _make_scene(scene_id="s1", frame_id="f1", frame_title="First")
        mgr.handle_framed_scene(s1, owner_fd=10)

        assert "s1" in mgr._frames["f1"].scenes

        # Move s1 to frame f2
        s1_moved = _make_scene(scene_id="s1", frame_id="f2", frame_title="Second")
        mgr.handle_framed_scene(s1_moved, owner_fd=10)

        # s1 should be in f2, not f1
        assert "s1" in mgr._frames["f2"].scenes
        assert mgr._scene_to_frame["s1"] == "f2"
        # f1 was the only scene — closing it should remove the frame
        assert "f1" not in mgr._frames

    def test_unframed_scene_moves_to_frame(self) -> None:
        """An unframed scene with matching id is dismissed when framed."""
        mgr, _ = _make_manager()
        # Add s1 as unframed
        s1 = _make_scene(scene_id="s1")
        mgr.handle_scene(s1, owner_fd=10)
        assert "s1" in mgr._scenes

        # Now send s1 into a frame
        s1_framed = _make_scene(scene_id="s1", frame_id="f1", frame_title="Frame")
        mgr.handle_framed_scene(s1_framed, owner_fd=10)

        # s1 should be gone from unframed scenes and present in frame
        assert "s1" not in mgr._scenes
        assert "s1" in mgr._frames["f1"].scenes


# -------------------------------------------------------------------
# 8. test_clear_all
# -------------------------------------------------------------------


class TestClearAll:
    def test_everything_empty(self) -> None:
        """clear_all empties all scene-related state."""
        mgr, _ = _make_manager()

        # Add unframed and framed scenes
        s1 = _make_scene(scene_id="s1")
        mgr.handle_scene(s1, owner_fd=10)
        s2 = _make_scene(scene_id="s2", frame_id="f1", frame_title="Frame")
        mgr.handle_framed_scene(s2, owner_fd=10)

        mgr.clear_all()

        assert len(mgr._scenes) == 0
        assert len(mgr._scene_order) == 0
        assert mgr._active_tab is None
        assert len(mgr._frames) == 0
        assert len(mgr._scene_to_frame) == 0
        assert len(mgr._scene_to_owner) == 0
        assert len(mgr._scene_widget_state) == 0
        assert len(mgr._dirty_windows) == 0

    def test_clear_all_idempotent(self) -> None:
        """Calling clear_all on empty state does not fail."""
        mgr, _ = _make_manager()
        mgr.clear_all()
        assert mgr._active_tab is None
