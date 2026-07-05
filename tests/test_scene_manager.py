"""Characterization tests for SceneManager extraction from DisplayServer.

These tests verify scene management behavior: adding scenes, replacing them,
framing, dismissing, updating, and clearing.  They test SceneManager directly
as a pure state machine — no ImGui, no sockets, no DisplayServer.
"""

from __future__ import annotations

import pytest

from punt_lux.protocol import (
    ButtonElement,
    GroupElement,
    InputNumberElement,
    Patch,
    SceneMessage,
    SeparatorElement,
    SliderElement,
    TextElement,
    UpdateMessage,
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
# 6. test_apply_update
# -------------------------------------------------------------------


class TestApplyUpdate:
    def test_patch_modifies_element(self) -> None:
        """An UpdateMessage with a set patch modifies element fields."""
        mgr, _ = _make_manager()
        scene = _make_scene(elements=[TextElement(id="t1", content="Original")])
        mgr.handle_scene(scene, owner_fd=10)

        update = UpdateMessage(
            scene_id="s1",
            patches=[Patch(id="t1", set={"content": "Updated"})],
        )
        mgr.apply_update(update)

        assert mgr._scenes["s1"].elements[0].content == "Updated"  # type: ignore[union-attr]

    def test_patch_removes_element(self) -> None:
        """A patch with remove=True removes the element from the scene."""
        mgr, _ = _make_manager()
        scene = _make_scene(
            elements=[
                TextElement(id="t1", content="Keep"),
                TextElement(id="t2", content="Remove"),
            ]
        )
        mgr.handle_scene(scene, owner_fd=10)

        update = UpdateMessage(
            scene_id="s1",
            patches=[Patch(id="t2", remove=True)],
        )
        mgr.apply_update(update)

        ids = [getattr(e, "id", None) for e in mgr._scenes["s1"].elements]
        assert "t2" not in ids
        assert "t1" in ids

    def test_update_nonexistent_scene_is_noop(self) -> None:
        """Updating a scene that doesn't exist does nothing."""
        mgr, _ = _make_manager()
        update = UpdateMessage(
            scene_id="no-such-scene",
            patches=[Patch(id="t1", set={"content": "X"})],
        )
        # Should not raise
        mgr.apply_update(update)

    def test_patch_cannot_change_id_or_kind(self) -> None:
        """Patches must not modify id or kind fields."""
        mgr, _ = _make_manager()
        scene = _make_scene(elements=[TextElement(id="t1", content="Hello")])
        mgr.handle_scene(scene, owner_fd=10)

        update = UpdateMessage(
            scene_id="s1",
            patches=[Patch(id="t1", set={"id": "t999", "kind": "button"})],
        )
        mgr.apply_update(update)

        elem = mgr._scenes["s1"].elements[0]
        assert elem.id == "t1"
        assert elem.kind == "text"

    def test_patch_unknown_fields_raises(self) -> None:
        """Unknown field names in a patch raise ValueError instead of silent drop."""
        mgr, _ = _make_manager()
        scene = _make_scene(elements=[TextElement(id="t1", content="Hello")])
        mgr.handle_scene(scene, owner_fd=10)

        update = UpdateMessage(
            scene_id="s1",
            patches=[Patch(id="t1", set={"content": "Updated", "bogus_key": "x"})],
        )
        with pytest.raises(ValueError, match="bogus_key"):
            mgr.apply_update(update)

    def test_patch_all_unknown_fields_raises(self) -> None:
        """A patch containing only unknown fields raises ValueError."""
        mgr, _ = _make_manager()
        scene = _make_scene(elements=[TextElement(id="t1", content="Hello")])
        mgr.handle_scene(scene, owner_fd=10)

        update = UpdateMessage(
            scene_id="s1",
            patches=[Patch(id="t1", set={"nonexistent": "value"})],
        )
        with pytest.raises(ValueError, match="nonexistent"):
            mgr.apply_update(update)

    def test_patch_value_on_input_number_writes_widget_state(self) -> None:
        """Regression for code-reviewer IMPORTANT on f3bd2bb.

        InputNumberElement must provide widget_value() — otherwise a
        ``value`` patch sets WidgetState to ``None`` and the next render crashes
        on ``int(None)`` inside ``InputNumberRenderer._draw_input``.
        """
        mgr, _ = _make_manager()
        scene = _make_scene(
            elements=[InputNumberElement(id="in1", label="N", value=1.0)]
        )
        mgr.handle_scene(scene, owner_fd=10)
        ws = mgr.widget_state_for("s1")
        assert ws is not None

        update = UpdateMessage(
            scene_id="s1",
            patches=[Patch(id="in1", set={"value": 42.0})],
        )
        mgr.apply_update(update)

        # widget_value() returns elem.value — the patch must mirror into state.
        assert ws.get("in1") == 42.0

    def test_patch_value_on_slider_writes_widget_state(self) -> None:
        """Companion regression: SliderElement also writes its post-patch value."""
        mgr, _ = _make_manager()
        scene = _make_scene(elements=[SliderElement(id="sl1", label="Vol", value=0.5)])
        mgr.handle_scene(scene, owner_fd=10)
        ws = mgr.widget_state_for("s1")
        assert ws is not None

        update = UpdateMessage(
            scene_id="s1",
            patches=[Patch(id="sl1", set={"value": 7.5})],
        )
        mgr.apply_update(update)

        assert ws.get("sl1") == 7.5

    def test_patch_value_on_color_picker_discards_widget_state(self) -> None:
        """Regression for cumulative SFH HIGH finding on PR 2.

        ColorPickerElement is intentionally excluded from the widget_value()
        dispatch (the renderer caches an ``ImVec4`` whose shape the domain
        cannot produce).  Before this fix a ``value`` patch wrote ``None`` into
        WidgetState; the next render's ``ensure(eid, ImVec4(...))`` returned
        ``None`` (key present), and ``imgui.color_edit3(label, None)`` crashed
        or mis-rendered.

        The contract: patching a value on a class excluded from the
        widget_value() dispatch must DISCARD the cached entry so the next
        render re-seeds from the patched element fields.
        """
        from punt_lux.protocol.elements.color_picker import ColorPickerElement

        mgr, _ = _make_manager()
        scene = _make_scene(
            elements=[ColorPickerElement(id="cp1", label="Tint", value="#FF0000")]
        )
        mgr.handle_scene(scene, owner_fd=10)
        ws = mgr.widget_state_for("s1")
        assert ws is not None

        # Seed the cache the way the renderer would: with an ImVec4-shaped tuple.
        ws.set("cp1", (1.0, 0.0, 0.0, 1.0))
        assert ws.get("cp1") == (1.0, 0.0, 0.0, 1.0)

        update = UpdateMessage(
            scene_id="s1",
            patches=[Patch(id="cp1", set={"value": "#00FF00"})],
        )
        mgr.apply_update(update)

        # Cache must be DISCARDED — not poisoned with None.  Next render's
        # ensure() will re-seed from elem.value via parse_rgba.  Use a
        # sentinel default to distinguish "key absent" from "key present
        # with value None" (the previous buggy state).
        sentinel = object()
        assert ws.get("cp1", sentinel) is sentinel

    def test_update_framed_scene(self) -> None:
        """Updates work for scenes inside frames."""
        mgr, _ = _make_manager()
        scene = _make_scene(
            elements=[TextElement(id="t1", content="Hello")],
            frame_id="f1",
            frame_title="Frame",
        )
        mgr.handle_framed_scene(scene, owner_fd=10)

        update = UpdateMessage(
            scene_id="s1",
            patches=[Patch(id="t1", set={"content": "Updated"})],
        )
        mgr.apply_update(update)

        frame_scene = mgr._frames["f1"].scenes["s1"]
        assert frame_scene.elements[0].content == "Updated"  # type: ignore[union-attr]


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


# -------------------------------------------------------------------
# 9. test_apply_update inside an all-ABC group (F8)
# -------------------------------------------------------------------


class TestApplyUpdateAbcGroup:
    """The state machine must traverse an all-ABC group's subtree.

    Before the Protocol-driven walk, ``find`` treated an all-ABC group as a
    childless leaf: a set-patch on a nested child was silently discarded and
    the child's id was never reported stale on scene replace.
    """

    @staticmethod
    def _abc_group_scene() -> SceneMessage:
        """A scene whose single element is a rows group with one text child."""
        group = GroupElement(
            id="g1",
            layout="rows",
            children=(TextElement(id="t1", content="Original"),),
        )
        return _make_scene(elements=[group])

    def test_set_patch_on_child_in_abc_group_is_applied(self) -> None:
        """A set-patch reaches a child nested in an all-ABC group."""
        mgr, _ = _make_manager()
        mgr.handle_scene(self._abc_group_scene(), owner_fd=10)

        mgr.apply_update(
            UpdateMessage(
                scene_id="s1",
                patches=[Patch(id="t1", set={"content": "Updated"})],
            )
        )

        group = mgr._scenes["s1"].elements[0]
        assert isinstance(group, GroupElement)
        # ABC elements patch IN PLACE — the group's own tuple entry changed.
        child = group.children[0]
        assert isinstance(child, TextElement)
        assert child.content == "Updated"

    def test_remove_patch_drops_abc_group_child_from_render(self) -> None:
        """A remove-patch physically drops the child from what the display paints.

        The display renders whatever the group's ``_children()`` yields, so
        the fix must remove the child from that tuple — not merely flip a
        ``_removed`` flag that the render path never consults. Assert the
        removed child is ABSENT from the render-visible children and the
        kept sibling survives.
        """
        mgr, _ = _make_manager()
        gone = TextElement(id="t1", content="x")
        kept = TextElement(id="t2", content="y")
        group = GroupElement(id="g1", layout="rows", children=(gone, kept))
        mgr.handle_scene(_make_scene(elements=[group]), owner_fd=10)

        mgr.apply_update(
            UpdateMessage(scene_id="s1", patches=[Patch(id="t1", remove=True)])
        )

        stored = mgr._scenes["s1"].elements[0]
        assert isinstance(stored, GroupElement)
        # ``children`` is the render source (== ``_children()``); the removed
        # child must be gone from it, so the Display no longer paints it.
        rendered_ids = [c.id for c in stored.children]
        assert "t1" not in rendered_ids
        assert rendered_ids == ["t2"]

    def test_scene_replace_reports_child_in_abc_group_stale(self) -> None:
        """Replacing the scene reports the nested child's id stale."""
        mgr, stale_calls = _make_manager()
        mgr.handle_scene(self._abc_group_scene(), owner_fd=10)

        mgr.handle_scene(
            _make_scene(elements=[TextElement(id="t2", content="New")]),
            owner_fd=10,
        )

        assert len(stale_calls) == 1
        assert "t1" in stale_calls[0]
        assert "g1" in stale_calls[0]
