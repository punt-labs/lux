"""Unit tests for FrameBook — the frame collection split out of SceneManager."""

from __future__ import annotations

from punt_lux.protocol import SceneMessage, TextElement
from punt_lux.scene.frame_book import FrameBook


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
        book.focus_frame_id = "f1"
        popped = book.pop_frame("f1")
        assert popped is not None
        assert popped.frame_id == "f1"
        assert "f1" not in book.frames
        assert book.focus_frame_id is None

    def test_pop_keeps_focus_on_a_different_frame(self) -> None:
        book = FrameBook()
        book.ensure(_scene(scene_id="s1"), "f1", owner_fd=10)
        book.ensure(_scene(scene_id="s2"), "f2", owner_fd=10)
        book.focus_frame_id = "f2"
        book.pop_frame("f1")
        assert book.focus_frame_id == "f2"

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
        book.focus_frame_id = "f1"
        book.clear()
        assert not book.frames
        assert not book.scene_to_frame
        assert not book.scene_to_owner
        assert book.focus_frame_id is None
