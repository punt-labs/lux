"""SceneEviction — taking a scene out of its frame and settling the frame left."""

from __future__ import annotations

from typing import Self, final

from punt_lux.display.replica.frame import Frame
from punt_lux.display.replica.frame_book import FrameBook
from punt_lux.display.replica.owner_facts_cache import OwnerFactsStore
from punt_lux.display.replica.scene_eviction import SceneEviction
from punt_lux.domain.identity import HubId, HubScopedKey
from punt_lux.protocol import SceneMessage, TextElement

_HUB = HubId.stub()
_OLD = (("Client", "departed"),)
_NEW = (("Client", "survivor"),)
_FRAME = HubScopedKey(_HUB, "f")


@final
class _Disposer:
    """Answers 'emptied' on request and records the disposals."""

    _emptied: bool
    disposed: list[str]
    __slots__ = ("_emptied", "disposed")

    def __new__(cls, *, emptied: bool) -> Self:
        self = super().__new__(cls)
        self._emptied = emptied
        self.disposed = []
        return self

    def dismiss_framed_scene(self, frame: Frame, scene_id: str) -> bool:
        return self._emptied

    def dispose_frame(self, frame_id: str, hub: HubId) -> list[str]:
        self.disposed.append(frame_id)
        return []


def _eviction(
    *, emptied: bool
) -> tuple[SceneEviction, FrameBook, OwnerFactsStore, _Disposer]:
    book, facts, disposer = FrameBook(), OwnerFactsStore(), _Disposer(emptied=emptied)
    facts.adopt(_FRAME, _OLD)
    return SceneEviction(book, facts, disposer), book, facts, disposer


def _hold(book: FrameBook, scene_id: str) -> Frame:
    msg = SceneMessage(
        id=scene_id,
        elements=[TextElement(id=f"t-{scene_id}", content="x")],
        frame_id="f",
    )
    frame = book.ensure(msg, 1, _HUB)
    frame.scene_order.append(scene_id)
    book.set_frame(HubScopedKey(_HUB, scene_id), "f")
    return frame


def test_a_frame_the_eviction_emptied_is_disposed() -> None:
    eviction, book, _, disposer = _eviction(emptied=True)

    eviction.from_frame(_hold(book, "s1"), "s1", _NEW)

    assert disposer.disposed == ["f"]


def test_a_frame_that_stays_occupied_takes_the_hubs_facts() -> None:
    eviction, book, facts, _ = _eviction(emptied=False)

    eviction.from_frame(_hold(book, "s1"), "s1", _NEW)

    assert facts.rows_for(_FRAME) == _NEW


def test_a_frame_that_stays_occupied_forgets_the_owner_when_the_hub_says_none() -> None:
    eviction, book, facts, _ = _eviction(emptied=False)

    eviction.from_frame(_hold(book, "s1"), "s1", None)

    assert facts.rows_for(_FRAME) is None


def test_a_frame_that_stays_occupied_is_not_disposed() -> None:
    eviction, book, _, disposer = _eviction(emptied=False)

    eviction.from_frame(_hold(book, "s1"), "s1", None)

    assert disposer.disposed == []


def test_eviction_from_the_holder_finds_the_frame_by_the_scene() -> None:
    eviction, book, facts, _ = _eviction(emptied=False)
    _hold(book, "s1")

    eviction.from_holder(HubScopedKey(_HUB, "s1"), _NEW, None)

    assert facts.rows_for(_FRAME) == _NEW


def test_eviction_from_the_holder_of_an_unheld_scene_touches_nothing() -> None:
    eviction, _, facts, disposer = _eviction(emptied=True)

    eviction.from_holder(HubScopedKey(_HUB, "ghost"), _NEW, None)

    assert (facts.rows_for(_FRAME), disposer.disposed) == (_OLD, [])


def test_a_junior_scene_leaving_keeps_the_frames_owner_facts() -> None:
    eviction, book, facts, _ = _eviction(emptied=False)
    _hold(book, "senior")
    frame = _hold(book, "junior")

    eviction.from_frame(frame, "junior", None)

    assert facts.rows_for(_FRAME) == _OLD


def test_a_junior_scene_leaving_ignores_the_facts_the_trigger_carried() -> None:
    eviction, book, facts, _ = _eviction(emptied=False)
    _hold(book, "senior")
    frame = _hold(book, "junior")

    eviction.from_frame(frame, "junior", _NEW)

    assert facts.rows_for(_FRAME) == _OLD


def test_the_senior_scene_leaving_clears_the_facts_when_none_were_carried() -> None:
    eviction, book, facts, _ = _eviction(emptied=False)
    frame = _hold(book, "senior")
    _hold(book, "junior")

    eviction.from_frame(frame, "senior", None)

    assert facts.rows_for(_FRAME) is None


def test_the_senior_scene_leaving_adopts_the_facts_the_trigger_carried() -> None:
    eviction, book, facts, _ = _eviction(emptied=False)
    frame = _hold(book, "senior")
    _hold(book, "junior")

    eviction.from_frame(frame, "senior", _NEW)

    assert facts.rows_for(_FRAME) == _NEW


def test_a_scene_the_frame_does_not_hold_is_not_senior() -> None:
    eviction, book, facts, _ = _eviction(emptied=False)
    frame = _hold(book, "senior")

    eviction.from_frame(frame, "ghost", None)

    assert facts.rows_for(_FRAME) == _OLD


class TestTheScopeLabel:
    """A frame's scope label is replaced only when the Hub speaks (an empty push)."""

    def test_closing_the_oldest_tab_keeps_the_label(self) -> None:
        eviction, book, _, _ = _eviction(emptied=False)
        senior = _hold(book, "senior")
        _hold(book, "junior")
        senior.heading.scope_label = "lux"

        eviction.from_frame(senior, "senior", None)

        assert senior.heading.scope_label == "lux"

    def test_re_framing_the_oldest_scene_elsewhere_keeps_the_label(self) -> None:
        eviction, book, _, _ = _eviction(emptied=False)
        frame = _hold(book, "senior")
        _hold(book, "junior")
        frame.heading.scope_label = "lux (2)"

        eviction.from_frame(frame, "senior", _NEW)

        assert frame.heading.scope_label == "lux (2)"

    def test_an_empty_push_for_the_oldest_scene_takes_the_hubs_label(self) -> None:
        eviction, book, _, _ = _eviction(emptied=False)
        frame = _hold(book, "senior")
        _hold(book, "junior")
        frame.heading.scope_label = "lux"

        eviction.from_holder(HubScopedKey(_HUB, "senior"), _NEW, "lux (2)")

        assert frame.heading.scope_label == "lux (2)"

    def test_an_empty_push_for_the_oldest_scene_takes_the_hubs_absence(self) -> None:
        eviction, book, _, _ = _eviction(emptied=False)
        frame = _hold(book, "senior")
        _hold(book, "junior")
        frame.heading.scope_label = "lux"

        eviction.from_holder(HubScopedKey(_HUB, "senior"), None, None)

        assert frame.heading.scope_label is None

    def test_an_empty_push_for_a_junior_scene_leaves_the_label(self) -> None:
        eviction, book, _, _ = _eviction(emptied=False)
        _hold(book, "senior")
        frame = _hold(book, "junior")
        frame.heading.scope_label = "lux"

        eviction.from_holder(HubScopedKey(_HUB, "junior"), None, "other")

        assert frame.heading.scope_label == "lux"

    def test_an_emptied_frame_is_disposed_whatever_label_arrives(self) -> None:
        eviction, book, _, disposer = _eviction(emptied=True)
        _hold(book, "s1")

        eviction.from_holder(HubScopedKey(_HUB, "s1"), None, "lux")

        assert disposer.disposed == ["f"]
