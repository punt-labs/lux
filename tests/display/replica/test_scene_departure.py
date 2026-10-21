"""SceneDeparture — dropping scenes from frames, disposing a frame left empty."""

from __future__ import annotations

from typing import Self, final

from punt_lux.display.replica.frame import Frame
from punt_lux.display.replica.frame_book import FrameBook
from punt_lux.display.replica.owner_facts_cache import OwnerFactsStore
from punt_lux.display.replica.scene_departure import SceneDeparture
from punt_lux.domain.identity import HubId, HubScopedKey
from punt_lux.protocol import SceneMessage, TextElement

_HUB = HubId.stub()
_ROWS = (("Client", "lux"),)


def _scene(scene_id: str, frame_id: str, *, empty: bool = False) -> SceneMessage:
    return SceneMessage(
        id=scene_id,
        elements=[] if empty else [TextElement(id=f"t-{scene_id}", content="Hi")],
        frame_id=frame_id,
        frame_owner_facts=_ROWS,
    )


@final
class _Disposer:
    """Record the replica calls a departure makes, answering 'emptied' on request."""

    _emptied: bool
    dismissed: list[tuple[str, str]]
    disposed: list[str]
    __slots__ = ("_emptied", "dismissed", "disposed")

    def __new__(cls, *, emptied: bool) -> Self:
        self = super().__new__(cls)
        self._emptied = emptied
        self.dismissed = []
        self.disposed = []
        return self

    def dismiss_framed_scene(self, frame: Frame, scene_id: str) -> bool:
        self.dismissed.append((frame.frame_id, scene_id))
        return self._emptied

    def dispose_frame(self, frame_id: str, hub: HubId) -> list[str]:
        self.disposed.append(frame_id)
        return []


def _departure(
    disposer: _Disposer,
) -> tuple[SceneDeparture, FrameBook, OwnerFactsStore]:
    book, facts = FrameBook(), OwnerFactsStore()
    return SceneDeparture(book, facts, disposer), book, facts


def _hold(book: FrameBook, scene_id: str, frame_id: str) -> Frame:
    frame = book.ensure(_scene(scene_id, frame_id), 1, _HUB)
    book.set_frame(HubScopedKey(_HUB, scene_id), frame_id)
    return frame


def test_an_empty_push_for_a_held_scene_dismisses_it() -> None:
    disposer = _Disposer(emptied=False)
    departure, book, _ = _departure(disposer)
    _hold(book, "s1", "f")

    departure.of_empty_push(HubScopedKey(_HUB, "s1"), _ROWS)

    assert disposer.dismissed == [("f", "s1")]


def test_a_frame_the_removal_emptied_is_disposed() -> None:
    disposer = _Disposer(emptied=True)
    departure, book, _ = _departure(disposer)
    _hold(book, "s1", "f")

    departure.of_empty_push(HubScopedKey(_HUB, "s1"), _ROWS)

    assert disposer.disposed == ["f"]


def test_a_frame_the_removal_left_occupied_is_kept() -> None:
    disposer = _Disposer(emptied=False)
    departure, book, _ = _departure(disposer)
    _hold(book, "s1", "f")

    departure.of_empty_push(HubScopedKey(_HUB, "s1"), _ROWS)

    assert disposer.disposed == []


def test_an_empty_push_for_an_unheld_scene_touches_nothing() -> None:
    disposer = _Disposer(emptied=True)
    departure, _, facts = _departure(disposer)

    departure.of_empty_push(HubScopedKey(_HUB, "ghost"), _ROWS)

    assert (disposer.dismissed, facts.rows_for(HubScopedKey(_HUB, "f"))) == ([], None)


def test_a_scene_leaves_the_other_frame_that_holds_it() -> None:
    disposer = _Disposer(emptied=False)
    departure, book, _ = _departure(disposer)
    _hold(book, "s1", "old")
    new = _hold(book, "s2", "new")

    departure.from_other_frame(new, HubScopedKey(_HUB, "s1"))

    assert disposer.dismissed == [("old", "s1")]


def test_a_scene_already_in_the_target_frame_is_left_alone() -> None:
    disposer = _Disposer(emptied=True)
    departure, book, _ = _departure(disposer)
    frame = _hold(book, "s1", "f")

    departure.from_other_frame(frame, HubScopedKey(_HUB, "s1"))

    assert disposer.dismissed == []
