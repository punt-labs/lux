"""Characterization tests for SceneReplica extraction from RenderLoop.

These tests verify scene management behavior: adding scenes, replacing them,
framing, dismissing, updating, and clearing.  They test SceneReplica directly
as a pure state machine — no ImGui, no sockets, no RenderLoop.
"""

from __future__ import annotations

from punt_lux.display.replica import SceneReplica, WidgetState
from punt_lux.protocol import (
    ButtonElement,
    SceneMessage,
    SeparatorElement,
    TableElement,
    TextElement,
)


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
    """Build a SceneMessage, self-framing by its scene id when no frame is named.

    Every scene is framed — the Hub synthesizes ``frame_id = scene_id`` at the
    render boundary when a caller names none — so the default here mirrors that.
    """
    if elements is None:
        elements = [
            TextElement(id="t1", content="Hello", style="heading"),
            ButtonElement(id="b1", label="Click"),
            SeparatorElement(),
        ]
    return SceneMessage(
        id=scene_id,
        elements=elements,  # type: ignore[arg-type]
        frame_id=frame_id if frame_id is not None else scene_id,
        frame_title=frame_title,
        frame_size=frame_size,
        frame_flags=frame_flags,
        frame_layout=frame_layout,  # type: ignore[arg-type]
        title=title,
    )


def _make_manager() -> tuple[SceneReplica, list[list[str]]]:
    """Create a SceneReplica with captured stale-id callbacks.

    Returns (manager, stale_calls) where stale_calls collects every
    call to the on_scene_replaced callback.
    """
    stale_calls: list[list[str]] = []

    def on_replaced(stale_ids: list[str]) -> None:
        stale_calls.append(stale_ids)

    mgr = SceneReplica(on_scene_replaced=on_replaced)
    return mgr, stale_calls


class TestEmptyPushIsRemoval:
    """An empty element push is a scene removal — the intended semantics.

    ``show(scene_id, [])`` dismisses the scene rather than leaving an empty window;
    a scene whose tree still holds an element (a zero-row table is one
    ``TableElement``) is kept. Documents the boundary so the direct-empty-show
    change stays deliberate and the beads zero-rows case stays safe.
    """

    def test_empty_element_push_dismisses_the_scene(self) -> None:
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene("s1"), owner_fd=10)
        assert mgr.resolve_scene("s1") is not None

        mgr.handle_framed_scene(_make_scene("s1", elements=[]), owner_fd=10)
        assert mgr.resolve_scene("s1") is None  # removed, not an empty husk

    def test_a_zero_row_table_is_not_a_removal(self) -> None:
        mgr, _ = _make_manager()
        table = TableElement(id="tbl", columns=["A"], rows=[])
        mgr.handle_framed_scene(_make_scene("s1", elements=[table]), owner_fd=10)
        assert mgr.resolve_scene("s1") is not None  # a TableElement is kept


# -------------------------------------------------------------------
# 1. test_handle_scene_new
# -------------------------------------------------------------------


class TestHandleSceneNew:
    def test_scene_appears_in_state(self) -> None:
        """A new scene populates its frame, order, active_tab, and widget state."""
        mgr, _ = _make_manager()
        scene = _make_scene()

        mgr.handle_framed_scene(scene, owner_fd=10)

        frame = mgr.frames["s1"]
        assert "s1" in frame.scenes
        assert frame.scene_order == ["s1"]
        assert frame.active_tab == "s1"
        assert isinstance(mgr.widget_state_for("s1"), WidgetState)


# -------------------------------------------------------------------
# 2. test_handle_scene_replace
# -------------------------------------------------------------------


class TestHandleSceneReplace:
    def test_replacement_overwrites_scene(self) -> None:
        """Sending a scene with the same id into its frame replaces the previous one."""
        mgr, stale_calls = _make_manager()
        first = _make_scene(elements=[TextElement(id="t1", content="First")])
        second = _make_scene(elements=[TextElement(id="t2", content="Second")])

        mgr.handle_framed_scene(first, owner_fd=10)
        mgr.handle_framed_scene(second, owner_fd=10)

        frame = mgr.frames["s1"]
        assert frame.scenes["s1"].elements[0].id == "t2"
        assert frame.scene_order == ["s1"]
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
        mgr.handle_framed_scene(_make_scene(), owner_fd=10)
        ws = mgr.widget_state_for("s1")
        assert ws is not None
        ws.set("t1", "survivor")
        ws.set("__tbl_sel_t1", 3)
        ws.set("b1", "stale")
        ws.set("b1__open", True)
        ws.set("__tbl_sel_b1", 5)

        replacement = _make_scene(elements=[TextElement(id="t1", content="New")])
        mgr.handle_framed_scene(replacement, owner_fd=10)

        assert ws.get("t1") == "survivor"
        assert ws.get("__tbl_sel_t1") == 3
        assert ws.get("b1") is None
        assert ws.get("b1__open") is None
        assert ws.get("__tbl_sel_b1") == 5

    def test_replace_keeps_events_for_id_another_frame_still_holds(self) -> None:
        """Replacing a scene keeps events for an id a scene in another frame holds.

        A whole-root re-push drains the ids the replaced scene dropped — but only
        those no other framed scene holds. When a scene in a second frame shares an
        element id, replacing the first scene with content that drops that id must
        not report it stale: its queued events remain valid inside the other frame.
        """
        mgr, stale_calls = _make_manager()
        shared: list[object] = [ButtonElement(id="shared", label="Click")]
        mgr.handle_framed_scene(
            _make_scene(scene_id="s1", frame_id="f0", elements=shared), owner_fd=10
        )
        mgr.handle_framed_scene(
            _make_scene(scene_id="s2", frame_id="f1", elements=shared), owner_fd=11
        )

        replacement = _make_scene(
            scene_id="s1", frame_id="f0", elements=[TextElement(id="t2", content="New")]
        )
        mgr.handle_framed_scene(replacement, owner_fd=10)

        drained = [sid for call in stale_calls for sid in call]
        assert "shared" not in drained

    def test_replace_drains_id_no_other_scene_holds(self) -> None:
        """A dropped id held by no other scene is drained on replacement.

        The survivor-aware control for the shared-id case: with only one scene
        holding the id, replacing that scene away must drain its queued events.
        """
        mgr, stale_calls = _make_manager()
        mgr.handle_framed_scene(
            _make_scene(
                scene_id="s1", elements=[ButtonElement(id="only", label="Click")]
            ),
            owner_fd=10,
        )

        replacement = _make_scene(
            scene_id="s1", elements=[TextElement(id="t2", content="New")]
        )
        mgr.handle_framed_scene(replacement, owner_fd=10)

        drained = [sid for call in stale_calls for sid in call]
        assert "only" in drained

    def test_replace_resets_honoured_but_keeps_survivor_state(self) -> None:
        """A re-push resets echo-suppression bookkeeping, keeps user state.

        A surviving tab bar's ``:active_honoured`` key is per-render-session
        bookkeeping: it must reset so the first post-re-push frame re-honours the
        Hub-authoritative active tab instead of reading a stale value and firing a
        spurious ``TabChanged``. The survivor's selection state is untouched.
        """
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene(), owner_fd=10)
        ws = mgr.widget_state_for("s1")
        assert ws is not None
        ws.set(f"t1{WidgetState.HONOURED_SUFFIX}", "tab-2")
        ws.set("__tbl_sel_t1", 3)

        replacement = _make_scene(elements=[TextElement(id="t1", content="New")])
        mgr.handle_framed_scene(replacement, owner_fd=10)

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

        assert "f1" in mgr.frames
        frame = mgr.frames["f1"]
        assert frame.title == "My Frame"
        assert "s1" in frame.scenes
        assert frame.scene_order == ["s1"]
        assert mgr.scene_to_frame["s1"] == "f1"
        assert mgr.scene_to_owner["s1"] == 10
        # N1: born on screen, and that is all. A push is a notification, not a
        # window-raise, so nothing asks for focus.
        assert frame.is_on_screen is True
        assert mgr.consume_focus("f1") is False

    def test_second_scene_joins_frame(self) -> None:
        """A second scene with the same frame_id is added to the frame."""
        mgr, _ = _make_manager()
        s1 = _make_scene(scene_id="s1", frame_id="f1", frame_title="Frame")
        s2 = _make_scene(scene_id="s2", frame_id="f1")

        mgr.handle_framed_scene(s1, owner_fd=10)
        mgr.handle_framed_scene(s2, owner_fd=11)

        frame = mgr.frames["f1"]
        assert set(frame.scenes.keys()) == {"s1", "s2"}
        assert frame.scene_order == ["s1", "s2"]
        assert frame.owner_fds == {10, 11}
        # N2: it joins the strip; the visibility, the focus and the user's tab
        # are all left where they were.
        assert frame.is_on_screen is True
        assert frame.active_tab == "s1"
        assert mgr.consume_focus("f1") is False


# -------------------------------------------------------------------
# 4. test_dismiss_scene
# -------------------------------------------------------------------


class TestDismissScene:
    def test_cleanup_and_next_tab_selection(self) -> None:
        """Dismissing a scene from a frame removes its state and re-picks the tab."""
        mgr, _ = _make_manager()
        frame_id = "f1"
        for sid in ("s1", "s2", "s3"):
            mgr.handle_framed_scene(
                _make_scene(scene_id=sid, frame_id=frame_id), owner_fd=10
            )
        frame = mgr.frames[frame_id]
        frame.active_tab = "s2"

        empty = mgr.dismiss_framed_scene(frame, "s2")

        assert empty is False
        assert "s2" not in frame.scenes
        assert "s2" not in frame.scene_order
        assert mgr.widget_state_for("s2") is None
        # The dismissed active tab yields to the frame's first remaining scene.
        assert frame.active_tab == "s1"

    def test_dismiss_last_scene_empties_the_frame(self) -> None:
        """Dismissing the only scene reports the frame empty and clears its tab."""
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene(), owner_fd=10)
        frame = mgr.frames["s1"]

        empty = mgr.dismiss_framed_scene(frame, "s1")

        assert empty is True
        assert frame.active_tab is None
        assert len(frame.scenes) == 0

    def test_shared_id_across_frames_survives_one_dismissal(self) -> None:
        """Dismissing a scene keeps events for an id a scene in another frame holds.

        Stale-event draining keys on element id alone. When two scenes in separate
        frames share an element id, dismissing one must not report that id stale —
        the other frame's queued events remain valid.
        """
        mgr, stale_calls = _make_manager()
        shared: list[object] = [ButtonElement(id="shared", label="Click")]
        mgr.handle_framed_scene(
            _make_scene(scene_id="s1", frame_id="f0", elements=shared), owner_fd=10
        )
        mgr.handle_framed_scene(
            _make_scene(scene_id="s2", frame_id="f1", elements=shared), owner_fd=11
        )

        mgr.dismiss_framed_scene(mgr.frames["f0"], "s1")

        drained = [sid for call in stale_calls for sid in call]
        assert "shared" not in drained


# -------------------------------------------------------------------
# 5. dispose_frame and close — one method that was two operations
# -------------------------------------------------------------------


class TestDisposeFrame:
    """The content half: the client says its content is gone, so it goes."""

    def test_frame_and_scene_state_cleaned(self) -> None:
        """Disposing a frame removes the frame and all its scenes."""
        mgr, _ = _make_manager()
        s1 = _make_scene(scene_id="s1", frame_id="f1", frame_title="Frame")
        s2 = _make_scene(scene_id="s2", frame_id="f1")

        mgr.handle_framed_scene(s1, owner_fd=10)
        mgr.handle_framed_scene(s2, owner_fd=10)

        stale_ids = mgr.dispose_frame("f1")

        assert "f1" not in mgr.frames
        assert "s1" not in mgr.scene_to_frame
        assert "s2" not in mgr.scene_to_frame
        assert mgr.widget_state_for("s1") is None
        assert mgr.widget_state_for("s2") is None
        assert "s1" not in mgr.scene_to_owner
        assert "s2" not in mgr.scene_to_owner
        # stale_ids should include element ids from the dismissed scenes
        assert len(stale_ids) > 0

    def test_dispose_nonexistent_frame(self) -> None:
        """Disposing a frame that doesn't exist returns empty stale list."""
        mgr, _ = _make_manager()
        stale_ids = mgr.dispose_frame("no-such-frame")
        assert stale_ids == []

    def test_focus_frame_cleared(self) -> None:
        """If the disposed frame was focused, its focus request is cleared."""
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), owner_fd=10)
        mgr.request_focus("f1")

        mgr.dispose_frame("f1")

        assert mgr.consume_focus("f1") is False

    def test_a_closed_frame_is_disposed_like_any_other(self) -> None:
        """D7 — the husk rule ignores visibility, so a closed frame is not a leak.

        Putting a window away is not a claim on its content: when the client
        takes that content back, the frame goes with it whatever the user had
        made of it, and the ids return to never-seen.
        """
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), owner_fd=10)
        mgr.close("f1")

        mgr.dispose_frame("f1")

        assert "f1" not in mgr.frames
        assert "s1" not in mgr.scene_to_frame
        assert mgr.widget_state_for("s1") is None

    def test_an_empty_push_disposes_a_closed_frames_last_scene(self) -> None:
        """D7 through the real entry point: the Hub blanks a scene the user shut."""
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), owner_fd=10)
        mgr.close("f1")

        mgr.handle_framed_scene(
            _make_scene(scene_id="s1", frame_id="f1", elements=[]), owner_fd=10
        )

        assert "f1" not in mgr.frames
        assert mgr.resolve_scene("s1") is None

    def test_a_frame_id_reused_after_a_disposal_is_genuinely_new(self) -> None:
        """The user's close applied to a frame that no longer exists."""
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), owner_fd=10)
        mgr.close("f1")
        mgr.dispose_frame("f1")

        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), owner_fd=10)

        assert mgr.frames["f1"].is_on_screen is True


class TestClose:
    """The visibility half: the user shut a window, which says nothing about content.

    Every assertion here is one half of the split — what closing does *not* do is
    as much the point as what it does. It used to do all of it under one name,
    which is how a track change came to reopen a window the user had shut.
    """

    def test_a_closed_frame_stays_in_the_book_holding_its_scenes(self) -> None:
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), owner_fd=10)

        mgr.close("f1")

        assert mgr.frames["f1"].is_closed is True
        assert mgr.resolve_scene("s1") is not None

    def test_closing_a_docked_frame_closes_it(self) -> None:
        """X2 — closed is reachable from the dock as well as from the screen."""
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), owner_fd=10)
        mgr.minimize("f1")

        mgr.close("f1")

        assert mgr.frames["f1"].is_closed is True
        assert mgr.docked_frames() == []

    def test_the_scene_ids_are_not_forgotten(self) -> None:
        """X3 — "known" survives a close. This is bug B's mechanism, not its symptom.

        If closing still called ``forget_scene`` the id would return to *unseen*
        and the next background push would read as an arrival.
        """
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), owner_fd=10)

        mgr.close("f1")

        assert mgr.scene_to_frame["s1"] == "f1"
        assert mgr.scene_to_owner["s1"] == 10

    def test_widget_state_survives_a_close(self) -> None:
        """X4 — scroll, selection and half-typed text survive a close.

        They survive a minimize today for exactly the same reason: the user put
        the window away, they did not throw its contents out.
        """
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), owner_fd=10)
        ws = mgr.widget_state_for("s1")
        assert ws is not None
        ws.set("input_x", "half-typed")
        ws.set("__tbl_sel_t1", 3)

        mgr.close("f1")

        assert mgr.widget_state_for("s1") is ws
        assert ws.get("input_x") == "half-typed"
        assert ws.get("__tbl_sel_t1") == 3

    def test_closing_notifies_no_stale_element_ids(self) -> None:
        """X5 — nothing was replaced, so nothing is stale to anyone but this Display."""
        mgr, stale_calls = _make_manager()
        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), owner_fd=10)
        stale_calls.clear()

        mgr.close("f1")

        assert stale_calls == []

    def test_closing_returns_the_scene_ids_for_the_caller_to_drain(self) -> None:
        """X6's half of the contract: a shut window's button must not fire later.

        Scene ids, not element ids. An element id is shareable across scenes, so
        draining by id would reach into a frame still on screen; a scene id names
        this frame's own work and nothing else. The survivor-aware stale path
        cannot do the job either — the elements *do* survive a close.
        """
        mgr, _ = _make_manager()
        for sid in ("s1", "s2"):
            mgr.handle_framed_scene(_make_scene(scene_id=sid, frame_id="f1"), 10)

        assert mgr.close("f1") == ["s1", "s2"]

    def test_closing_names_no_scene_of_a_frame_that_stays_up(self) -> None:
        """The drain list is one frame's, even when another shares an element id."""
        mgr, _ = _make_manager()
        shared: list[object] = [ButtonElement(id="save", label="Save")]
        mgr.handle_framed_scene(
            _make_scene(scene_id="s1", frame_id="f1", elements=shared), 10
        )
        mgr.handle_framed_scene(
            _make_scene(scene_id="s2", frame_id="f2", elements=shared), 10
        )

        assert mgr.close("f1") == ["s1"]

    def test_closing_clears_a_focus_request_that_frame_held(self) -> None:
        """X7 — a frame that is not painted cannot take focus."""
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), owner_fd=10)
        mgr.request_focus("f1")

        mgr.close("f1")

        assert mgr.consume_focus("f1") is False

    def test_closing_a_frame_that_is_not_up_is_a_noop(self) -> None:
        """X9 — an answer, not an error."""
        mgr, _ = _make_manager()
        assert mgr.close("no-such-frame") == []

    def test_closing_leaves_the_active_tab_and_cascade_index_alone(self) -> None:
        """Nothing about a closed frame is destroyed; it is simply not painted."""
        mgr, _ = _make_manager()
        for sid in ("s1", "s2"):
            mgr.handle_framed_scene(_make_scene(scene_id=sid, frame_id="f1"), 10)
        frame = mgr.frames["f1"]
        frame.active_tab = "s2"
        cascade_index = frame.cascade_index

        mgr.close("f1")

        assert frame.active_tab == "s2"
        assert frame.cascade_index == cascade_index


class TestActiveSceneId:
    """The display's single 'current' scene is one it is actually showing."""

    def test_it_is_the_first_painted_frames_tab(self) -> None:
        mgr, _ = _make_manager()
        for fid, sid in (("f1", "s1"), ("f2", "s2")):
            mgr.handle_framed_scene(_make_scene(scene_id=sid, frame_id=fid), 10)

        assert mgr.active_scene_id == "s1"

    def test_it_skips_a_closed_frame(self) -> None:
        """V8 — a frame the user shut is not what the display is showing."""
        mgr, _ = _make_manager()
        for fid, sid in (("f1", "s1"), ("f2", "s2")):
            mgr.handle_framed_scene(_make_scene(scene_id=sid, frame_id=fid), 10)

        mgr.close("f1")

        assert mgr.active_scene_id == "s2"

    def test_it_skips_a_docked_frame(self) -> None:
        mgr, _ = _make_manager()
        for fid, sid in (("f1", "s1"), ("f2", "s2")):
            mgr.handle_framed_scene(_make_scene(scene_id=sid, frame_id=fid), 10)

        mgr.minimize("f1")

        assert mgr.active_scene_id == "s2"

    def test_it_is_none_when_nothing_is_painted(self) -> None:
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), 10)

        mgr.close("f1")

        assert mgr.active_scene_id is None


# -------------------------------------------------------------------
# 7. test_upsert_scene_dedup
# -------------------------------------------------------------------


class TestUpsertSceneDedup:
    def test_scene_moves_between_frames(self) -> None:
        """Sending the same scene to a second frame removes it from the first."""
        mgr, _ = _make_manager()
        s1 = _make_scene(scene_id="s1", frame_id="f1", frame_title="First")
        mgr.handle_framed_scene(s1, owner_fd=10)

        assert "s1" in mgr.frames["f1"].scenes

        # Move s1 to frame f2
        s1_moved = _make_scene(scene_id="s1", frame_id="f2", frame_title="Second")
        mgr.handle_framed_scene(s1_moved, owner_fd=10)

        # s1 should be in f2, not f1
        assert "s1" in mgr.frames["f2"].scenes
        assert mgr.scene_to_frame["s1"] == "f2"
        # f1 was the only scene — closing it should remove the frame
        assert "f1" not in mgr.frames


class TestAPushNeverWritesVisibility:
    """A content event never writes visibility — the whole of DES-065 R8.

    The user owns where a frame is and which tab is showing. A push is a
    notification: whether the scene is brand new to the frame or the tenth
    repaint of one already there, it may not pull a docked frame back up, reopen
    a window the user shut, take focus from where they are working, or move them
    off the tab they chose.

    The cross product of *is the scene new* against *what the user made of the
    frame* is written out rather than sampled, because the uniformity of the
    answer --- nothing changes, in every cell --- is the rule itself.
    """

    def test_a_replace_leaves_a_docked_frame_docked(self) -> None:
        """R2."""
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene(frame_id="f1"), owner_fd=10)
        mgr.minimize("f1")

        mgr.handle_framed_scene(_make_scene(frame_id="f1"), owner_fd=10)

        assert mgr.frames["f1"].is_docked is True
        assert mgr.consume_focus("f1") is False

    def test_a_replace_leaves_a_closed_frame_closed(self) -> None:
        """R3 — bug B's partition, in the shape voxd meets it on a track change."""
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene(frame_id="f1"), owner_fd=10)
        mgr.close("f1")

        mgr.handle_framed_scene(_make_scene(frame_id="f1"), owner_fd=10)

        assert mgr.frames["f1"].is_closed is True
        assert mgr.consume_focus("f1") is False

    def test_a_push_after_a_close_is_a_repeat_not_an_arrival(self) -> None:
        """R5 — bug B's mechanism, and the one assertion that cannot pass by accident.

        The close no longer forgets the scene, so the same id pushed again is a
        repaint of something known rather than an arrival. If ``close`` still
        called ``forget_scene``, this push would take the ``is_new`` branch and
        the frame would come back on screen.
        """
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), owner_fd=10)
        frame = mgr.frames["f1"]
        mgr.close("f1")

        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), owner_fd=10)

        assert frame.is_closed is True
        assert frame.scene_order == ["s1"], "the id was re-added, so it read as new"
        assert mgr.consume_focus("f1") is False

    def test_a_new_scene_leaves_a_docked_frame_docked(self) -> None:
        """N3 — the partition that used to assert the opposite by name."""
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), 10)
        mgr.minimize("f1")

        mgr.handle_framed_scene(_make_scene(scene_id="s2", frame_id="f1"), 10)

        assert mgr.frames["f1"].is_docked is True
        assert mgr.consume_focus("f1") is False
        assert mgr.frames["f1"].active_tab == "s1"

    def test_a_new_scene_leaves_a_closed_frame_closed(self) -> None:
        """N4 — a second board arriving does not reopen the window the user shut."""
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), 10)
        mgr.close("f1")

        mgr.handle_framed_scene(_make_scene(scene_id="s2", frame_id="f1"), 10)

        assert mgr.frames["f1"].is_closed is True
        assert mgr.consume_focus("f1") is False
        assert "s2" in mgr.frames["f1"].scenes, "the scene still arrived, unseen"

    def test_a_replace_leaves_the_foreground_frame_focused(self) -> None:
        """F3 — no content event ever leaves a focus request, whoever held it."""
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene(scene_id="board", frame_id="f1"), 10)
        mgr.handle_framed_scene(_make_scene(scene_id="notes", frame_id="f2"), 10)
        mgr.raise_frame("f2")  # the user put f2 in front

        mgr.handle_framed_scene(_make_scene(scene_id="board", frame_id="f1"), 10)

        assert mgr.consume_focus("f1") is False
        assert mgr.consume_focus("f2") is True

    def test_no_push_ever_leaves_a_focus_request(self) -> None:
        """F3 over the whole cross product: new frame, new scene, and repeat alike."""
        mgr, _ = _make_manager()

        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), 10)
        assert mgr.consume_focus("f1") is False

        mgr.handle_framed_scene(_make_scene(scene_id="s2", frame_id="f1"), 10)
        assert mgr.consume_focus("f1") is False

        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), 10)
        assert mgr.consume_focus("f1") is False

    def test_a_replace_leaves_the_tab_the_user_picked(self) -> None:
        """R4."""
        mgr, _ = _make_manager()
        for sid in ("s1", "s2"):
            mgr.handle_framed_scene(_make_scene(scene_id=sid, frame_id="f1"), 10)
        frame = mgr.frames["f1"]
        frame.active_tab = "s1"  # the user clicked back to the first tab

        mgr.handle_framed_scene(_make_scene(scene_id="s2", frame_id="f1"), 10)

        assert frame.active_tab == "s1"

    def test_a_new_scene_does_not_take_the_tab_from_the_user(self) -> None:
        """N2 / F2 — a selection is user-owned, in the same category as visibility.

        A second scene arriving in a frame the user is reading joins the strip;
        it does not pull them off what they were looking at.
        """
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), 10)
        frame = mgr.frames["f1"]

        mgr.handle_framed_scene(_make_scene(scene_id="s2", frame_id="f1"), 10)

        assert frame.active_tab == "s1"
        assert frame.scene_order == ["s1", "s2"]

    def test_a_frames_first_scene_does_take_the_tab(self) -> None:
        """N5 — the one legitimate tab write from content: there was no selection."""
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), 10)

        assert mgr.frames["f1"].active_tab == "s1"

    def test_a_scene_moving_frames_writes_neither_frames_visibility(self) -> None:
        """R6 — a content-to-content relocation is still a content event."""
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene(scene_id="keep", frame_id="f1"), 10)
        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), 10)
        mgr.handle_framed_scene(_make_scene(scene_id="other", frame_id="f2"), 10)
        mgr.minimize("f1")
        mgr.close("f2")

        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f2"), 10)

        assert mgr.frames["f1"].is_docked is True
        assert mgr.frames["f2"].is_closed is True
        assert mgr.consume_focus("f2") is False

    def test_a_raise_survives_the_next_background_push(self) -> None:
        """A6 — the push does not undo the gesture, in either direction."""
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), 10)
        mgr.close("f1")
        mgr.raise_frame("f1")
        mgr.consume_focus("f1")

        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), 10)

        assert mgr.frames["f1"].is_on_screen is True


# -------------------------------------------------------------------
# 8. test_clear_all
# -------------------------------------------------------------------


class TestClearAll:
    def test_everything_empty(self) -> None:
        """clear_all empties all scene-related state."""
        mgr, _ = _make_manager()

        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f0"), owner_fd=10)
        mgr.handle_framed_scene(
            _make_scene(scene_id="s2", frame_id="f1", frame_title="Frame"), owner_fd=10
        )

        mgr.clear_all()

        assert len(mgr.frames) == 0
        assert mgr.scene_count == 0
        assert len(mgr.scene_to_frame) == 0
        assert len(mgr.scene_to_owner) == 0
        assert mgr.widget_state_count == 0

    def test_clear_all_idempotent(self) -> None:
        """Calling clear_all on empty state does not fail."""
        mgr, _ = _make_manager()
        mgr.clear_all()
        assert len(mgr.frames) == 0


class TestWidgetStateDiscardFor:
    def test_clears_dialog_latches_so_re_add_reopens(self) -> None:
        """Removing a dialog id clears its latches so a re-added dialog reopens.

        A dismissed dialog leaves ``{id}__dismissed`` set to open. The adapter
        reads that latch with a closed default, so unless the discard happens a
        re-added same-id dialog reads the stale open value and never opens.
        """
        ws = WidgetState()
        ws.set("confirm", "answered")
        ws.set("confirm__open", 1)
        ws.set("confirm__dismissed", 1)

        ws.discard_for("confirm")

        assert ws.get("confirm") is None
        assert ws.get("confirm__open") is None
        assert ws.get("confirm__dismissed") is None
        assert ws.get("confirm__dismissed", 0) == 0

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

    def test_clears_the_header_open_pending_key(self) -> None:
        """Removing an id clears its ``:header_open_pending`` key.

        The slot holds the open state a ``HeaderToggled`` is outstanding for. A
        re-added same-id collapsing header must show the state the Hub declared
        for it, not a departed header's in-flight toggle.
        """
        ws = WidgetState()
        ws.set(f"h{WidgetState.HEADER_OPEN_PENDING_SUFFIX}", True)

        ws.discard_for("h")

        assert ws.get(f"h{WidgetState.HEADER_OPEN_PENDING_SUFFIX}") is None


class TestWidgetStateResetSessionSlots:
    def test_discards_every_honoured_key(self) -> None:
        """``reset_session_slots`` forgets every tab bar's last force-selected tab."""
        ws = WidgetState()
        ws.set(f"tb1{WidgetState.HONOURED_SUFFIX}", "a")
        ws.set(f"tb2{WidgetState.HONOURED_SUFFIX}", "b")

        ws.reset_session_slots()

        assert ws.get(f"tb1{WidgetState.HONOURED_SUFFIX}") is None
        assert ws.get(f"tb2{WidgetState.HONOURED_SUFFIX}") is None

    def test_discards_every_pending_key(self) -> None:
        """``reset_session_slots`` forgets every tab bar's outstanding-fire tab too.

        On a re-push the Hub becomes authoritative again, so the pending slot
        that suppressed the click-to-re-push window must clear — otherwise it
        would keep gagging a genuine switch after the window has closed.
        """
        ws = WidgetState()
        ws.set(f"tb1{WidgetState.PENDING_SUFFIX}", "a")
        ws.set(f"tb2{WidgetState.PENDING_SUFFIX}", "b")

        ws.reset_session_slots()

        assert ws.get(f"tb1{WidgetState.PENDING_SUFFIX}") is None
        assert ws.get(f"tb2{WidgetState.PENDING_SUFFIX}") is None

    def test_discards_every_header_open_key(self) -> None:
        """``reset_session_slots`` forgets every header's optimistic open flag.

        The re-push carries the Hub's answer, so the value a ``HeaderToggled``
        was fired for must stop winning — that is what lets a toggle the Hub
        rejects pull the display back instead of stranding it.
        """
        ws = WidgetState()
        ws.set(f"h1{WidgetState.HEADER_OPEN_PENDING_SUFFIX}", True)
        ws.set(f"h2{WidgetState.HEADER_OPEN_PENDING_SUFFIX}", False)

        ws.reset_session_slots()

        assert ws.get(f"h1{WidgetState.HEADER_OPEN_PENDING_SUFFIX}") is None
        assert ws.get(f"h2{WidgetState.HEADER_OPEN_PENDING_SUFFIX}") is None

    def test_preserves_user_transient_state(self) -> None:
        """Only session slots reset — selection, scroll, and text survive."""
        ws = WidgetState()
        ws.set(f"tb{WidgetState.HONOURED_SUFFIX}", "tab-1")
        ws.set(f"tb{WidgetState.PENDING_SUFFIX}", "tab-2")
        ws.set(f"h{WidgetState.HEADER_OPEN_PENDING_SUFFIX}", True)
        ws.set("__tbl_sel_tb", 4)
        ws.set("input_x", "half-typed")

        ws.reset_session_slots()

        assert ws.get(f"tb{WidgetState.HONOURED_SUFFIX}") is None
        assert ws.get(f"tb{WidgetState.PENDING_SUFFIX}") is None
        assert ws.get(f"h{WidgetState.HEADER_OPEN_PENDING_SUFFIX}") is None
        assert ws.get("__tbl_sel_tb") == 4
        assert ws.get("input_x") == "half-typed"


# -------------------------------------------------------------------
# Empty scene removes its frame — no husk frames (ruling 1)
# -------------------------------------------------------------------


class TestEmptySceneRemovesFrame:
    """An emptied scene push removes the frame; content and frame vanish together."""

    def test_empty_framed_scene_closes_its_only_frame(self) -> None:
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(
            _make_scene(
                scene_id="s1",
                frame_id="f1",
                elements=[TextElement(id="t1", content="Hi")],
            ),
            owner_fd=10,
        )
        assert "f1" in mgr.frames

        # The Hub emptied the scene and blanked it — an empty framed push.
        mgr.handle_framed_scene(
            _make_scene(scene_id="s1", frame_id="f1", elements=[]),
            owner_fd=10,
        )
        assert "f1" not in mgr.frames  # gone, not a husk
        assert "s1" not in mgr.scene_to_frame
        assert mgr.resolve_scene("s1") is None

    def test_empty_framed_scene_keeps_a_frame_holding_other_scenes(self) -> None:
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(
            _make_scene(
                scene_id="s1",
                frame_id="f1",
                elements=[TextElement(id="t1", content="A")],
            ),
            owner_fd=10,
        )
        mgr.handle_framed_scene(
            _make_scene(
                scene_id="s2",
                frame_id="f1",
                elements=[TextElement(id="t2", content="B")],
            ),
            owner_fd=10,
        )
        mgr.handle_framed_scene(
            _make_scene(scene_id="s1", frame_id="f1", elements=[]),
            owner_fd=10,
        )
        assert "f1" in mgr.frames  # survives — s2 still holds it
        assert mgr.resolve_scene("s1") is None
        assert mgr.resolve_scene("s2") is not None

    def test_empty_framed_scene_for_an_absent_frame_is_a_noop(self) -> None:
        mgr, _ = _make_manager()
        # No frame ever created; an empty push must not raise or create one.
        mgr.handle_framed_scene(
            _make_scene(scene_id="s1", frame_id="f1", elements=[]),
            owner_fd=10,
        )
        assert "f1" not in mgr.frames


class TestScenesToPurge:
    """DES-068's manifest-driven purge query — every ghost scene, not frame."""

    def test_a_scene_outside_the_manifest_and_owner_is_a_candidate(self) -> None:
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), owner_fd=10)

        candidates = mgr.scenes_to_purge(identifying_fd=20, manifest=frozenset())

        assert candidates == [("f1", "s1")]

    def test_a_scene_named_in_the_manifest_is_not_a_candidate(self) -> None:
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), owner_fd=10)

        candidates = mgr.scenes_to_purge(identifying_fd=20, manifest=frozenset({"s1"}))

        assert candidates == []

    def test_a_scene_owned_by_the_identifying_fd_is_not_a_candidate(self) -> None:
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), owner_fd=10)

        candidates = mgr.scenes_to_purge(identifying_fd=10, manifest=frozenset())

        assert candidates == []

    def test_a_mixed_frame_loses_only_its_ghost_scene(self) -> None:
        """Per-scene: a manifested scene shields its frame, not its ghost sibling."""
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), owner_fd=10)
        mgr.handle_framed_scene(_make_scene(scene_id="s2", frame_id="f1"), owner_fd=10)

        candidates = mgr.scenes_to_purge(identifying_fd=20, manifest=frozenset({"s1"}))

        assert candidates == [("f1", "s2")]

    def test_an_orphaned_scene_is_swept_by_the_same_rule(self) -> None:
        """A scene reassigned to the orphan sentinel is a candidate like any other.

        No special-casing needed: an orphan's owner is never the identifying
        fd, so it falls out of the same not-owned-and-not-manifested test.
        """
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), owner_fd=10)
        mgr.reassign_scenes_of(departed_fd=10, orphan_fd=-1)

        candidates = mgr.scenes_to_purge(identifying_fd=20, manifest=frozenset())

        assert candidates == [("f1", "s1")]

    def test_widget_state_is_discarded_only_for_the_purged_scene(self) -> None:
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), owner_fd=10)
        mgr.handle_framed_scene(_make_scene(scene_id="s2", frame_id="f1"), owner_fd=10)

        for frame_id, scene_id in mgr.scenes_to_purge(
            identifying_fd=20, manifest=frozenset({"s1"})
        ):
            frame = mgr.frames[frame_id]
            mgr.dismiss_framed_scene(frame, scene_id)

        assert mgr.widget_state_for("s2") is None  # purged
        assert mgr.widget_state_for("s1") is not None  # retained, untouched


class TestFramesOnlyInvariant:
    """The unframed scene path is gone: every scene lives in a frame or nowhere."""

    def test_no_unframed_scene_api_remains(self) -> None:
        # Fork-completion: the unframed branch was removed, not shimmed. The
        # storage and its handlers must be absent, not merely unused.
        surface = set(dir(SceneReplica))
        removed = {"handle_scene", "dismiss_scene", "scenes", "scene_order"}
        assert removed.isdisjoint(surface), surface & removed

    def test_resolve_scene_is_none_for_an_absent_scene(self) -> None:
        mgr, _ = _make_manager()
        assert mgr.resolve_scene("ghost") is None

    def test_resolve_scene_reads_through_the_frame(self) -> None:
        mgr, _ = _make_manager()
        mgr.handle_framed_scene(_make_scene(scene_id="s1", frame_id="f1"), owner_fd=10)
        resolved = mgr.resolve_scene("s1")
        assert resolved is not None
        assert resolved is mgr.frames["f1"].scenes["s1"]
