"""Unit tests for ScenePresentation and its per-scene registry."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from punt_lux.domain.hub.scene_presentation import (
    ScenePresentation,
    ScenePresentationRegistry,
)
from punt_lux.domain.ids import SceneId

if TYPE_CHECKING:
    from punt_lux.domain.element import Element as WireElement


class _RecordingPusher:
    """Capture the one ``show_async`` call a presentation makes."""

    calls: list[dict[str, object]]

    def __new__(cls) -> _RecordingPusher:
        self = super().__new__(cls)
        self.calls = []
        return self

    def show_async(
        self,
        scene_id: str,
        elements: list[WireElement],
        *,
        title: str | None = None,
        layout: str = "single",
        frame_id: str | None = None,
        frame_title: str | None = None,
        frame_size: tuple[int, int] | None = None,
        frame_flags: dict[str, bool] | None = None,
        frame_layout: Literal["tab", "stack"] | None = None,
    ) -> None:
        self.calls.append(
            {
                "scene_id": scene_id,
                "elements": elements,
                "title": title,
                "layout": layout,
                "frame_id": frame_id,
                "frame_title": frame_title,
                "frame_size": frame_size,
                "frame_flags": frame_flags,
                "frame_layout": frame_layout,
            }
        )


def test_recorded_presentation_is_returned() -> None:
    reg = ScenePresentationRegistry()
    pres = ScenePresentation(frame_id="hello-frame", frame_title="Hello")
    reg.record(SceneId("hello-scene"), pres)
    assert reg.presentation_for(SceneId("hello-scene")) == pres


def test_unrecorded_scene_falls_back_to_a_self_framed_default() -> None:
    reg = ScenePresentationRegistry()
    assert reg.presentation_for(SceneId("s1")) == ScenePresentation(frame_id="s1")
    assert reg.presentation_for(SceneId("s1")).frame_id == "s1"


def test_record_overwrites_a_prior_presentation() -> None:
    reg = ScenePresentationRegistry()
    reg.record(SceneId("s1"), ScenePresentation(frame_id="frame-a"))
    reg.record(SceneId("s1"), ScenePresentation(frame_id="frame-b"))
    assert reg.presentation_for(SceneId("s1")).frame_id == "frame-b"


def test_forget_reverts_to_the_scene_id_fallback() -> None:
    reg = ScenePresentationRegistry()
    reg.record(SceneId("s1"), ScenePresentation(frame_id="custom-frame"))
    reg.forget(SceneId("s1"))
    assert reg.presentation_for(SceneId("s1")).frame_id == "s1"


def test_forget_is_idempotent_on_an_unrecorded_scene() -> None:
    reg = ScenePresentationRegistry()
    reg.forget(SceneId("never-shown"))  # no-op, must not raise
    assert reg.presentation_for(SceneId("never-shown")).frame_id == "never-shown"


def test_push_resends_every_presentation_field() -> None:
    pres = ScenePresentation(
        frame_id="board",
        title="Board",
        layout="single",
        frame_title="Beads: lux",
        frame_size=(640, 480),
        frame_flags={"no_resize": True},
        frame_layout="stack",
    )
    pusher = _RecordingPusher()
    pres.push(pusher, SceneId("beads"), [])
    (call,) = pusher.calls
    assert call["scene_id"] == "beads"
    assert call["frame_id"] == "board"
    assert call["frame_title"] == "Beads: lux"
    assert call["frame_size"] == (640, 480)
    assert call["frame_flags"] == {"no_resize": True}
    assert call["frame_layout"] == "stack"
    assert call["title"] == "Board"
