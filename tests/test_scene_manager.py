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

    def test_replace_preserves_survivor_state_discards_stale(self) -> None:
        """A re-push keeps survivors' state and clears the departed's latches.

        A narrow ``update`` re-pushes the whole root; each element that left the
        tree has its bare id key and its ``__open``/``__dismissed`` latches
        discarded so a re-added same-id element starts fresh. The default scene
        has ``t1`` and ``b1``; the replacement keeps ``t1`` (selection and its
        decorated table key survive) and drops ``b1`` (bare key and open latch
        cleared). ``b1``'s table key embeds the id at the end, so it lingers
        until scene clear — cosmetic, never a functional break.
        """
        mgr, _ = _make_manager()
        mgr.handle_scene(_make_scene(), owner_fd=10)
        ws = mgr._scene_widget_state["s1"]
        ws.set("t1", "survivor")
        ws.set("__tbl_sel_t1", 3)
        ws.set("b1", "stale")
        ws.set("b1__open", True)
        ws.set("__tbl_sel_b1", 5)

        replacement = _make_scene(elements=[TextElement(id="t1", content="New")])
        mgr.handle_scene(replacement, owner_fd=10)

        assert ws.get("t1") == "survivor"
        assert ws.get("__tbl_sel_t1") == 3
        assert ws.get("b1") is None
        assert ws.get("b1__open") is None
        assert ws.get("__tbl_sel_b1") == 5

    def test_replace_resets_honoured_but_keeps_survivor_state(self) -> None:
        """A re-push resets echo-suppression bookkeeping, keeps user state.

        A surviving tab bar's ``:active_honoured`` key is per-render-session
        bookkeeping: it must reset so the first post-re-push frame re-honours the
        Hub-authoritative active tab instead of reading a stale value and firing a
        spurious ``TabChanged``. The survivor's selection state is untouched.
        """
        mgr, _ = _make_manager()
        mgr.handle_scene(_make_scene(), owner_fd=10)
        ws = mgr._scene_widget_state["s1"]
        ws.set(f"t1{WidgetState.HONOURED_SUFFIX}", "tab-2")
        ws.set("__tbl_sel_t1", 3)

        replacement = _make_scene(elements=[TextElement(id="t1", content="New")])
        mgr.handle_scene(replacement, owner_fd=10)

        assert ws.get(f"t1{WidgetState.HONOURED_SUFFIX}") is None
        assert ws.get("__tbl_sel_t1") == 3


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

    def test_shared_id_in_frame_survives_unframed_dismissal(self) -> None:
        """Dismissing an unframed scene keeps events for an id a frame still holds.

        Stale-event draining keys on element id alone. When a framed scene and an
        unframed scene share an element id, dismissing the unframed one must not
        report that id stale — its queued events remain valid inside the frame.
        """
        mgr, stale_calls = _make_manager()
        shared: list[object] = [ButtonElement(id="shared", label="Click")]
        mgr.handle_scene(_make_scene(scene_id="s1", elements=shared), owner_fd=10)
        mgr.handle_framed_scene(
            _make_scene(scene_id="s2", frame_id="f1", elements=shared), owner_fd=11
        )

        mgr.dismiss_scene("s1")

        drained = [sid for call in stale_calls for sid in call]
        assert "shared" not in drained


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


class TestWidgetStateDiscardFor:
    def test_clears_dialog_latches_so_re_add_reopens(self) -> None:
        """Removing a dialog id clears its latches so a re-added dialog reopens.

        A dismissed dialog leaves ``{id}__dismissed`` set to open. ``ensure``
        seeds only an absent key, so unless the latch is discarded a re-added
        same-id dialog reads the stale open value and never opens. After
        ``discard_for`` a fresh ``ensure`` returns the caller's closed default.
        """
        ws = WidgetState()
        ws.set("confirm", "answered")
        ws.set("confirm__open", 1)
        ws.set("confirm__dismissed", 1)

        ws.discard_for("confirm")

        assert ws.get("confirm") is None
        assert ws.get("confirm__open") is None
        assert ws.get("confirm__dismissed") is None
        assert ws.ensure("confirm__dismissed", 0) == 0

    def test_discards_only_the_exact_id_key(self) -> None:
        """``discard_for`` drops the removed element's own bare-id key only."""
        ws = WidgetState()
        ws.set("btn", "bare")

        ws.discard_for("btn")

        assert ws.get("btn") is None

    def test_leaves_underscore_survivor_state_intact(self) -> None:
        """Removing ``btn`` never wipes survivor ``btn_ok`` — bare AND decorated."""
        ws = WidgetState()
        ws.set("btn", "gone")
        ws.set("btn_ok", "keep")
        ws.set("btn_ok__open", True)
        ws.set("__tbl_sel_btn_ok", 7)

        ws.discard_for("btn")

        assert ws.get("btn") is None
        assert ws.get("btn_ok") == "keep"
        assert ws.get("btn_ok__open") is True
        assert ws.get("__tbl_sel_btn_ok") == 7

    def test_leaves_other_elements_untouched(self) -> None:
        """Discarding one id keeps a token-adjacent id's state — ``t1`` vs ``t10``."""
        ws = WidgetState()
        ws.set("t1", "gone")
        ws.set("__tbl_sel_t10", 9)
        ws.set("t10__open", True)

        ws.discard_for("t1")

        assert ws.get("t1") is None
        assert ws.get("__tbl_sel_t10") == 9
        assert ws.get("t10__open") is True

    def test_empty_id_is_a_noop(self) -> None:
        """An empty id (a separator has none) discards nothing."""
        ws = WidgetState()
        ws.set("__tbl_sel_t1", 1)

        ws.discard_for("")

        assert ws.get("__tbl_sel_t1") == 1

    def test_clears_the_honoured_echo_suppression_key(self) -> None:
        """Removing an id clears its ``:active_honoured`` key.

        A re-added same-id tab bar must not inherit the departed one's honoured
        active tab, or its first frame would read a stale value instead of
        re-honouring the Hub selection.
        """
        ws = WidgetState()
        ws.set(f"tb{WidgetState.HONOURED_SUFFIX}", "tab-2")

        ws.discard_for("tb")

        assert ws.get(f"tb{WidgetState.HONOURED_SUFFIX}") is None

    def test_clears_the_pending_fire_suppression_key(self) -> None:
        """Removing an id clears its ``:active_pending`` key.

        The pending slot suppresses a re-fire through the click-to-re-push
        window. A re-added same-id tab bar must start with no outstanding fire,
        or a genuine first click could be swallowed as already-pending.
        """
        ws = WidgetState()
        ws.set(f"tb{WidgetState.PENDING_SUFFIX}", "tab-2")

        ws.discard_for("tb")

        assert ws.get(f"tb{WidgetState.PENDING_SUFFIX}") is None


class TestWidgetStateResetHonoured:
    def test_discards_every_honoured_key(self) -> None:
        """``reset_honoured`` forgets every tab bar's last force-selected tab."""
        ws = WidgetState()
        ws.set(f"tb1{WidgetState.HONOURED_SUFFIX}", "a")
        ws.set(f"tb2{WidgetState.HONOURED_SUFFIX}", "b")

        ws.reset_honoured()

        assert ws.get(f"tb1{WidgetState.HONOURED_SUFFIX}") is None
        assert ws.get(f"tb2{WidgetState.HONOURED_SUFFIX}") is None

    def test_discards_every_pending_key(self) -> None:
        """``reset_honoured`` forgets every tab bar's outstanding-fire tab too.

        On a re-push the Hub becomes authoritative again, so the pending slot
        that suppressed the click-to-re-push window must clear — otherwise it
        would keep gagging a genuine switch after the window has closed.
        """
        ws = WidgetState()
        ws.set(f"tb1{WidgetState.PENDING_SUFFIX}", "a")
        ws.set(f"tb2{WidgetState.PENDING_SUFFIX}", "b")

        ws.reset_honoured()

        assert ws.get(f"tb1{WidgetState.PENDING_SUFFIX}") is None
        assert ws.get(f"tb2{WidgetState.PENDING_SUFFIX}") is None

    def test_preserves_user_transient_state(self) -> None:
        """Only session slots reset — selection, scroll, and text survive."""
        ws = WidgetState()
        ws.set(f"tb{WidgetState.HONOURED_SUFFIX}", "tab-1")
        ws.set(f"tb{WidgetState.PENDING_SUFFIX}", "tab-2")
        ws.set("__tbl_sel_tb", 4)
        ws.set("input_x", "half-typed")

        ws.reset_honoured()

        assert ws.get(f"tb{WidgetState.HONOURED_SUFFIX}") is None
        assert ws.get(f"tb{WidgetState.PENDING_SUFFIX}") is None
        assert ws.get("__tbl_sel_tb") == 4
        assert ws.get("input_x") == "half-typed"
