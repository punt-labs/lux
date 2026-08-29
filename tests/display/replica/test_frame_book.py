"""Unit tests for FrameBook — the frame collection split out of SceneReplica."""

from __future__ import annotations

import pytest

from punt_lux.display.replica.frame_book import FrameBook
from punt_lux.protocol import SceneMessage, TextElement


def _scene(
    scene_id: str = "s1",
    *,
    frame_id: str = "f1",
    frame_title: str | None = None,
    frame_flags: dict[str, bool] | None = None,
    frame_layout: str | None = None,
) -> SceneMessage:
    return SceneMessage(
        id=scene_id,
        elements=[TextElement(id="t1", content="Hi")],
        frame_id=frame_id,
        frame_title=frame_title,
        frame_flags=frame_flags,
        frame_layout=frame_layout,  # type: ignore[arg-type]
    )


class TestEnsure:
    def test_creates_a_frame_on_first_use(self) -> None:
        book = FrameBook()
        frame = book.ensure(_scene(frame_title="Title"), "f1", owner_fd=10)
        assert frame.frame_id == "f1"
        assert frame.title == "Title"
        assert 10 in frame.owner_fds
        assert book.frames["f1"] is frame

    def test_titles_from_scene_title_then_frame_id_when_unset(self) -> None:
        book = FrameBook()
        frame = book.ensure(_scene(), "f1", owner_fd=10)
        assert frame.title == "f1"  # no frame_title, no scene title -> frame id

    def test_reuses_and_updates_an_existing_frame(self) -> None:
        book = FrameBook()
        first = book.ensure(_scene(), "f1", owner_fd=10)
        second = book.ensure(
            _scene(frame_title="New", frame_flags={"no_resize": True}),
            "f1",
            owner_fd=11,
        )
        assert second is first  # same frame reused
        assert first.owner_fds == {10, 11}
        assert first.title == "New"
        assert first.flags == {"no_resize": True}

    def test_cascade_index_fills_the_lowest_free_slot(self) -> None:
        book = FrameBook()
        book.ensure(_scene(scene_id="s1"), "f1", owner_fd=10)
        book.ensure(_scene(scene_id="s2"), "f2", owner_fd=10)
        assert book.frames["f1"].cascade_index == 0
        assert book.frames["f2"].cascade_index == 1
        # Dropping f1 frees index 0; the next frame reuses it, not index 2.
        book.pop_frame("f1")
        book.ensure(_scene(scene_id="s3"), "f3", owner_fd=10)
        assert book.frames["f3"].cascade_index == 0


class TestPlacementMaps:
    def test_set_frame_and_record_owner_then_forget(self) -> None:
        book = FrameBook()
        book.ensure(_scene(), "f1", owner_fd=10)
        book.set_frame("s1", "f1")
        book.record_owner("s1", 10)
        assert book.scene_to_frame["s1"] == "f1"
        assert book.scene_to_owner["s1"] == 10
        assert book.frame_of_scene("s1") is book.frames["f1"]

        book.forget_scene("s1")
        assert "s1" not in book.scene_to_frame
        assert "s1" not in book.scene_to_owner
        assert book.frame_of_scene("s1") is None

    def test_frame_of_scene_is_none_for_unknown_scene(self) -> None:
        assert FrameBook().frame_of_scene("nope") is None


class TestPopFrame:
    def test_pop_returns_frame_and_clears_focus_when_it_held_it(self) -> None:
        book = FrameBook()
        book.ensure(_scene(), "f1", owner_fd=10)
        book.request_focus("f1")
        popped = book.pop_frame("f1")
        assert popped is not None
        assert popped.frame_id == "f1"
        assert "f1" not in book.frames
        assert book.consume_focus("f1") is False  # focus cleared with the frame

    def test_pop_keeps_focus_on_a_different_frame(self) -> None:
        book = FrameBook()
        book.ensure(_scene(scene_id="s1"), "f1", owner_fd=10)
        book.ensure(_scene(scene_id="s2"), "f2", owner_fd=10)
        book.request_focus("f2")
        book.pop_frame("f1")
        assert book.consume_focus("f2") is True  # f2 still awaits focus

    def test_pop_absent_frame_is_none(self) -> None:
        assert FrameBook().pop_frame("ghost") is None


class TestFramedScenesAndClear:
    def test_framed_scenes_yields_every_held_scene(self) -> None:
        book = FrameBook()
        f1 = book.ensure(_scene(scene_id="s1"), "f1", owner_fd=10)
        f1.scenes["s1"] = _scene(scene_id="s1")
        f2 = book.ensure(_scene(scene_id="s2", frame_id="f2"), "f2", owner_fd=10)
        f2.scenes["s2"] = _scene(scene_id="s2", frame_id="f2")
        ids = {s.id for s in book.framed_scenes()}
        assert ids == {"s1", "s2"}

    def test_clear_drops_everything(self) -> None:
        book = FrameBook()
        book.ensure(_scene(), "f1", owner_fd=10)
        book.set_frame("s1", "f1")
        book.record_owner("s1", 10)
        book.request_focus("f1")
        book.clear()
        assert not book.frames
        assert not book.scene_to_frame
        assert not book.scene_to_owner
        assert book.consume_focus("f1") is False  # focus dropped by clear


class TestConsumeFocus:
    def test_consume_is_one_shot(self) -> None:
        book = FrameBook()
        book.request_focus("f1")
        assert book.consume_focus("f1") is True  # awaited focus, now cleared
        assert book.consume_focus("f1") is False  # not again

    def test_consume_of_an_unfocused_frame_is_false(self) -> None:
        book = FrameBook()
        book.request_focus("f1")
        assert book.consume_focus("f2") is False  # f2 never requested
        assert book.consume_focus("f1") is True  # f1's request still stands


class TestMinimize:
    def test_minimizes_a_present_frame(self) -> None:
        book = FrameBook()
        book.ensure(_scene(), "f1", owner_fd=10)
        book.minimize("f1")
        assert book.frames["f1"].is_docked is True

    def test_minimize_absent_frame_is_a_noop(self) -> None:
        FrameBook().minimize("ghost")  # no raise


class TestBornOnScreen:
    """A frame is born on screen, and that is the whole of the birth policy.

    The one place a content event may set a visibility, sound because there is
    no prior value to override. Being born on screen is not a raise: no focus is
    asked for, and no other frame is disturbed (partition N1).
    """

    def test_a_new_frame_is_on_screen(self) -> None:
        book = FrameBook()
        frame = book.ensure(_scene(), "f1", owner_fd=10)
        assert frame.is_on_screen is True

    def test_a_new_frame_asks_for_no_focus(self) -> None:
        book = FrameBook()
        book.ensure(_scene(), "f1", owner_fd=10)
        assert book.consume_focus("f1") is False

    def test_a_new_frame_leaves_another_frames_visibility_alone(self) -> None:
        book = FrameBook()
        book.ensure(_scene(), "f1", owner_fd=10)
        book.close("f1")

        book.ensure(_scene(scene_id="s2"), "f2", owner_fd=10)

        assert book.frames["f1"].is_closed is True

    def test_ensure_leaves_an_existing_frames_visibility_alone(self) -> None:
        """The policy is for frames being *born*; an existing one keeps its place."""
        book = FrameBook()
        book.ensure(_scene(), "f1", owner_fd=10)
        book.minimize("f1")

        book.ensure(_scene(), "f1", owner_fd=11)

        assert book.frames["f1"].is_docked is True


class TestClose:
    """Closing writes visibility and nothing else — the split's visibility half."""

    def test_a_closed_frame_stays_in_the_book(self) -> None:
        book = FrameBook()
        book.ensure(_scene(), "f1", owner_fd=10)

        book.close("f1")

        assert "f1" in book.frames
        assert book.frames["f1"].is_closed is True

    def test_closing_a_docked_frame_takes_away_its_pill(self) -> None:
        book = FrameBook()
        book.ensure(_scene(), "f1", owner_fd=10)
        book.minimize("f1")

        book.close("f1")

        assert book.docked() == []
        assert [f.frame_id for f in book.closed()] == ["f1"]

    def test_closing_clears_a_focus_request_that_frame_held(self) -> None:
        book = FrameBook()
        book.ensure(_scene(), "f1", owner_fd=10)
        book.request_focus("f1")

        book.close("f1")

        assert book.consume_focus("f1") is False

    def test_closing_leaves_another_frames_focus_request_standing(self) -> None:
        book = FrameBook()
        book.ensure(_scene(), "f1", owner_fd=10)
        book.ensure(_scene(scene_id="s2"), "f2", owner_fd=10)
        book.request_focus("f2")

        book.close("f1")

        assert book.consume_focus("f2") is True

    def test_closing_keeps_the_scene_placement_maps(self) -> None:
        """The user shut a window; that says nothing about what it holds."""
        book = FrameBook()
        book.ensure(_scene(), "f1", owner_fd=10)
        book.set_frame("s1", "f1")
        book.record_owner("s1", 10)

        book.close("f1")

        assert book.scene_to_frame["s1"] == "f1"
        assert book.scene_to_owner["s1"] == 10

    def test_closing_an_absent_frame_is_an_answer_not_an_error(self) -> None:
        assert FrameBook().close("ghost") is None


class TestRestore:
    """Restoring is one gesture, and it works from every visibility."""

    def test_restores_a_docked_frame_and_asks_for_focus(self) -> None:
        book = FrameBook()
        book.ensure(_scene(), "f1", owner_fd=10)
        book.minimize("f1")

        assert book.restore("f1") is True
        assert book.frames["f1"].is_on_screen is True
        assert book.consume_focus("f1") is True

    def test_restores_a_closed_frame_and_asks_for_focus(self) -> None:
        """Bug A's partition: the close left something for the gesture to act on."""
        book = FrameBook()
        book.ensure(_scene(), "f1", owner_fd=10)
        book.close("f1")

        assert book.restore("f1") is True
        assert book.frames["f1"].is_on_screen is True
        assert book.consume_focus("f1") is True

    def test_restores_a_frame_that_is_already_on_screen(self) -> None:
        book = FrameBook()
        book.ensure(_scene(), "f1", owner_fd=10)

        assert book.restore("f1") is True
        assert book.consume_focus("f1") is True

    def test_restoring_a_frame_the_book_does_not_hold_is_false(self) -> None:
        book = FrameBook()
        assert book.restore("ghost") is False
        assert book.consume_focus("ghost") is False


class TestVisibilityQueries:
    """The renderer and the menus ask the book, rather than testing a flag."""

    def test_each_frame_appears_in_exactly_one_bucket(self) -> None:
        book = FrameBook()
        for fid, sid in (("f1", "s1"), ("f2", "s2"), ("f3", "s3")):
            book.ensure(_scene(scene_id=sid), fid, owner_fd=10)
        book.minimize("f2")
        book.close("f3")

        assert [f.frame_id for f in book.on_screen()] == ["f1"]
        assert [f.frame_id for f in book.docked()] == ["f2"]
        assert [f.frame_id for f in book.closed()] == ["f3"]

    def test_the_buckets_are_empty_on_an_empty_book(self) -> None:
        book = FrameBook()
        assert book.on_screen() == []
        assert book.docked() == []
        assert book.closed() == []


class TestReassignScenesOf:
    def _framed_scene(self, book: FrameBook, scene_id: str, owner_fd: int) -> None:
        """Install a framed scene owned by ``owner_fd`` in frame ``f1``."""
        frame = book.ensure(_scene(scene_id=scene_id), "f1", owner_fd=owner_fd)
        frame.scene_order.append(scene_id)
        book.set_frame(scene_id, "f1")
        book.record_owner(scene_id, owner_fd)

    def test_transfers_to_a_surviving_co_owner(self) -> None:
        book = FrameBook()
        self._framed_scene(book, "s1", owner_fd=10)
        book.ensure(_scene(scene_id="s1"), "f1", owner_fd=11)  # second co-owner

        book.reassign_scenes_of(10, orphan_fd=-1)

        assert book.scene_to_owner["s1"] == 11
        assert 10 not in book.frames["f1"].owner_fds

    def test_orphans_when_no_owner_remains(self) -> None:
        book = FrameBook()
        self._framed_scene(book, "s1", owner_fd=10)

        book.reassign_scenes_of(10, orphan_fd=-1)

        assert book.scene_to_owner["s1"] == -1
        assert not book.frames["f1"].owner_fds

    def test_leaves_a_scene_another_client_owns_untouched(self) -> None:
        book = FrameBook()
        self._framed_scene(book, "s1", owner_fd=11)
        book.ensure(_scene(scene_id="s1"), "f1", owner_fd=10)  # departing co-owner

        book.reassign_scenes_of(10, orphan_fd=-1)

        assert book.scene_to_owner["s1"] == 11  # unchanged; 11 still owns it
        assert 10 not in book.frames["f1"].owner_fds


class TestReadOnlyViews:
    def test_frames_view_rejects_mutation(self) -> None:
        book = FrameBook()
        book.ensure(_scene(), "f1", owner_fd=10)
        with pytest.raises(TypeError):
            book.frames["f2"] = book.frames["f1"]  # type: ignore[index]

    def test_scene_maps_are_read_only(self) -> None:
        book = FrameBook()
        book.set_frame("s1", "f1")
        book.record_owner("s1", 10)
        with pytest.raises(TypeError):
            book.scene_to_frame["s2"] = "f9"  # type: ignore[index]
        with pytest.raises(TypeError):
            book.scene_to_owner["s2"] = 7  # type: ignore[index]
