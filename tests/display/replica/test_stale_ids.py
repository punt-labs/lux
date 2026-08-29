"""StaleIds — which element ids a change retired, and who has to be told.

The property that carries this class is that staleness is a claim about
*survival*, not about visibility: an id is stale only when no framed scene holds
it any more. A frame the user merely put away keeps every one of its ids alive,
which is why closing drains this Display's own queued interactions directly
rather than through :meth:`StaleIds.notify` (DES-088).
"""

from __future__ import annotations

from punt_lux.display.replica.frame_book import FrameBook
from punt_lux.display.replica.stale_ids import StaleIds
from punt_lux.protocol import (
    ButtonElement,
    SceneMessage,
    SeparatorElement,
    TextElement,
)


def _scene(scene_id: str, elements: list[object] | None = None) -> SceneMessage:
    if elements is None:
        elements = [
            TextElement(id="t1", content="Hello"),
            ButtonElement(id="b1", label="Click"),
        ]
    return SceneMessage(
        id=scene_id,
        elements=elements,  # type: ignore[arg-type]
        frame_id=scene_id,
    )


def _stale_ids() -> tuple[StaleIds, FrameBook, list[list[str]]]:
    """Return the collaborator over an empty book, with reports captured."""
    reported: list[list[str]] = []
    book = FrameBook()
    return StaleIds(book, reported.append), book, reported


def _install(book: FrameBook, msg: SceneMessage, frame_id: str) -> None:
    """Put a scene in a frame the way SceneReplica would, without its bookkeeping."""
    frame = book.ensure(msg, frame_id, owner_fd=10)
    frame.scenes[msg.id] = msg
    frame.scene_order.append(msg.id)
    book.set_frame(msg.id, frame_id)


class TestInTree:
    def test_it_collects_every_id_in_the_tree(self) -> None:
        stale, _book, _ = _stale_ids()
        assert stale.in_tree(_scene("s1").elements) == {"t1", "b1"}

    def test_an_element_with_no_id_contributes_nothing(self) -> None:
        """A separator cannot be addressed, so it is not an element id.

        Carrying an empty string through the drain or the stale report only puts
        a name on the wire that names nothing.
        """
        stale, _book, _ = _stale_ids()
        elements: list[object] = [
            TextElement(id="t1", content="Hi"),
            SeparatorElement(),
        ]

        assert stale.in_tree(elements) == {"t1"}

    def test_an_empty_tree_holds_no_ids(self) -> None:
        stale, _book, _ = _stale_ids()
        assert stale.in_tree([]) == set()


class TestOfFrame:
    def test_it_gathers_every_scene_in_the_frame(self) -> None:
        stale, book, _ = _stale_ids()
        _install(book, _scene("s1", [TextElement(id="a", content="A")]), "f1")
        _install(book, _scene("s2", [ButtonElement(id="b", label="B")]), "f1")

        assert stale.of_frame(book.frames["f1"]) == {"a", "b"}

    def test_an_empty_frame_holds_no_ids(self) -> None:
        stale, book, _ = _stale_ids()
        _install(book, _scene("s1"), "f1")
        frame = book.frames["f1"]
        frame.scenes.clear()

        assert stale.of_frame(frame) == set()


class TestDroppedBy:
    def test_it_reports_only_what_the_replacement_no_longer_carries(self) -> None:
        stale, _book, _ = _stale_ids()
        old = _scene(
            "s1", [TextElement(id="keep", content="A"), ButtonElement(id="go")]
        )
        new = _scene("s1", [TextElement(id="keep", content="B")])

        assert stale.dropped_by(new, old) == {"go"}

    def test_a_replacement_carrying_everything_drops_nothing(self) -> None:
        stale, _book, _ = _stale_ids()
        old = _scene("s1", [TextElement(id="keep", content="A")])
        new = _scene("s1", [TextElement(id="keep", content="B")])

        assert stale.dropped_by(new, old) == set()


class TestNotify:
    def test_an_id_no_scene_holds_is_reported(self) -> None:
        stale, _book, reported = _stale_ids()

        assert stale.notify({"gone"}) == ["gone"]
        assert reported == [["gone"]]

    def test_an_id_a_surviving_scene_still_holds_is_not_reported(self) -> None:
        """Survivor-aware: the ids are the workspace's, not one tree's.

        Two scenes in separate frames can share an element id; retiring one must
        not cancel the other's still-valid queued events.
        """
        stale, book, reported = _stale_ids()
        shared: list[object] = [ButtonElement(id="shared", label="Click")]
        _install(book, _scene("s1", shared), "f1")
        _install(book, _scene("s2", shared), "f2")

        assert stale.notify({"shared"}) == []
        assert reported == []

    def test_a_frame_the_user_closed_still_shields_its_ids(self) -> None:
        """Survival, not visibility. A closed frame's scenes are still held.

        This is the reason closing drains queued interactions directly instead of
        through this method: routed here, a close would report nothing at all.
        """
        stale, book, reported = _stale_ids()
        _install(book, _scene("s1", [ButtonElement(id="b1", label="Click")]), "f1")

        book.close("f1")

        assert stale.notify({"b1"}) == []
        assert reported == []

    def test_nothing_stale_means_nobody_is_told(self) -> None:
        stale, _book, reported = _stale_ids()

        assert stale.notify(set()) == []
        assert reported == []
