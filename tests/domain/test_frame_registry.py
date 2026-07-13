"""Unit tests for FrameRegistry — the scene→frame_id association."""

from __future__ import annotations

from punt_lux.domain.hub.frame_registry import FrameRegistry
from punt_lux.domain.ids import SceneId


def test_recorded_frame_is_returned() -> None:
    reg = FrameRegistry()
    reg.record(SceneId("hello-scene"), "hello-frame")
    assert reg.frame_for(SceneId("hello-scene")) == "hello-frame"


def test_unrecorded_scene_falls_back_to_its_own_id() -> None:
    # The default frame is named for the scene, so an unrecorded lookup is total.
    assert FrameRegistry().frame_for(SceneId("s1")) == "s1"


def test_record_overwrites_a_prior_frame() -> None:
    reg = FrameRegistry()
    reg.record(SceneId("s1"), "frame-a")
    reg.record(SceneId("s1"), "frame-b")
    assert reg.frame_for(SceneId("s1")) == "frame-b"


def test_frames_are_kept_per_scene() -> None:
    reg = FrameRegistry()
    reg.record(SceneId("a"), "frame-a")
    reg.record(SceneId("b"), "frame-b")
    assert reg.frame_for(SceneId("a")) == "frame-a"
    assert reg.frame_for(SceneId("b")) == "frame-b"
