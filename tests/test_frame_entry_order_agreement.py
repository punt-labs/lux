"""The Hub's frame entry order and the Display's ``Frame.scene_order`` agree.

The Display decides locally whether a departing scene was its frame's canonical
(oldest) one, while the Hub decides which owner the frame's facts describe. Both
must read the same order, so each case here replays one sequence of shows and
blanks into both and compares the order they keep for every frame.
"""

from __future__ import annotations

from typing import Literal

import pytest

from punt_lux.display.replica import SceneReplica
from punt_lux.domain.hub.scene_presentation import (
    ScenePresentation,
    ScenePresentationRegistry,
)
from punt_lux.domain.ids import SceneId
from punt_lux.protocol import Element, SceneMessage, TextElement

type _Step = tuple[Literal["show", "blank"], str, str]

_CASES: dict[str, list[_Step]] = {
    "join in sequence": [("show", "s1", "f"), ("show", "s2", "f"), ("show", "s3", "f")],
    "move into a frame lands last": [
        ("show", "s1", "a"),
        ("show", "s2", "shared"),
        ("show", "s1", "shared"),
    ],
    "re-show in place keeps the seat": [
        ("show", "s1", "f"),
        ("show", "s2", "f"),
        ("show", "s1", "f"),
    ],
    "blank then show re-enters last": [
        ("show", "s1", "f"),
        ("show", "s2", "f"),
        ("blank", "s1", "f"),
        ("show", "s1", "f"),
    ],
    "move out and back re-enters last": [
        ("show", "s1", "f"),
        ("show", "s2", "f"),
        ("show", "s1", "g"),
        ("show", "s1", "f"),
    ],
    "move leaves the others in place": [
        ("show", "s1", "f"),
        ("show", "s2", "f"),
        ("show", "s3", "f"),
        ("show", "s2", "g"),
    ],
}


def _ignore_stale(stale_ids: list[str]) -> None:
    """Take no interest in the element ids a replacement drops."""


def _message(scene_id: str, frame_id: str, *, empty: bool) -> SceneMessage:
    elements: list[Element] = []
    if not empty:
        elements.append(TextElement(id=f"t-{scene_id}", content="x"))
    return SceneMessage(id=scene_id, elements=elements, frame_id=frame_id)


@pytest.mark.parametrize("steps", _CASES.values(), ids=_CASES.keys())
def test_both_tiers_keep_the_same_order_for_every_frame(steps: list[_Step]) -> None:
    hub, display = (
        ScenePresentationRegistry(),
        SceneReplica(on_scene_replaced=_ignore_stale),
    )
    for verb, scene_id, frame_id in steps:
        if verb == "show":
            hub.record(SceneId(scene_id), ScenePresentation(frame_id=frame_id))
        else:
            hub.forget(SceneId(scene_id))
        display.handle_framed_scene(
            _message(scene_id, frame_id, empty=verb == "blank"), owner_fd=1
        )

    frame_ids = {frame_id for _, _, frame_id in steps}
    hub_order = {f: [str(s) for s in hub.scenes_in_frame(f)] for f in frame_ids}
    display_order = {
        f: list(frame.scene_order) if (frame := display.frame(f)) else []
        for f in frame_ids
    }
    assert hub_order == display_order
