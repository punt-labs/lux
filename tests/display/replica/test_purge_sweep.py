"""PurgeSweep — each orphan a manifest names leaves the frame still holding it."""

from __future__ import annotations

from typing import Self, final

from punt_lux.display.replica.frame import Frame
from punt_lux.display.replica.frame_book import FrameBook
from punt_lux.display.replica.owner_facts_cache import OwnerFactsStore
from punt_lux.display.replica.scene_departure import SceneDeparture
from punt_lux.domain.identity import HubId, HubScopedKey
from punt_lux.protocol import SceneMessage, TextElement

_HUB = HubId.stub()
_OTHER = HubId("other.invalid", 2)


@final
class _Disposer:
    """Records the dismissals a departure makes; every frame stays occupied."""

    dismissed: list[tuple[str, str]]
    __slots__ = ("dismissed",)

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.dismissed = []
        return self

    def dismiss_framed_scene(self, frame: Frame, scene_id: str) -> bool:
        self.dismissed.append((frame.frame_id, scene_id))
        return False

    def dispose_frame(self, frame_id: str, hub: HubId) -> list[str]:
        return []


def _departure() -> tuple[SceneDeparture, FrameBook, _Disposer]:
    book, disposer = FrameBook(), _Disposer()
    return SceneDeparture(book, OwnerFactsStore(), disposer), book, disposer


def _hold(book: FrameBook, scene_id: str, frame_id: str, hub: HubId = _HUB) -> None:
    msg = SceneMessage(
        id=scene_id,
        elements=[TextElement(id=f"t-{scene_id}", content="x")],
        frame_id=frame_id,
    )
    book.ensure(msg, 1, hub)
    book.set_frame(HubScopedKey(hub, scene_id), frame_id)


def test_a_scene_the_manifest_omits_is_dismissed_from_its_frame() -> None:
    departure, book, disposer = _departure()
    _hold(book, "s1", "f")

    departure.sweep.run(_HUB, frozenset(), frozenset({_HUB}))

    assert disposer.dismissed == [("f", "s1")]


def test_a_scene_the_manifest_names_is_left_alone() -> None:
    departure, book, disposer = _departure()
    _hold(book, "s1", "f")

    departure.sweep.run(_HUB, frozenset({"s1"}), frozenset({_HUB}))

    assert disposer.dismissed == []


def test_a_dead_hubs_scene_is_swept() -> None:
    departure, book, disposer = _departure()
    _hold(book, "s1", "f", _OTHER)

    departure.sweep.run(_HUB, frozenset(), frozenset({_HUB}))

    assert disposer.dismissed == [("f", "s1")]
