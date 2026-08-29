"""``FrameState``/``FrameStates`` -- the display's own frame-visibility read."""

from __future__ import annotations

from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.display_frames import FrameState, FrameStates

_VALID_FRAME = {
    "frame_id": "f1",
    "title": "Music",
    "scene_count": 1,
    "scene_ids": ["s1"],
    "layout": "tab",
    "visibility": "closed",
}


def test_from_payload_narrows_a_well_formed_reply() -> None:
    result = FrameStates.from_payload({"frames": [_VALID_FRAME]})

    assert isinstance(result, FrameStates)
    assert result.frames == [
        FrameState(frame_id="f1", title="Music", visibility="closed", scene_ids=["s1"])
    ]


def test_from_payload_accepts_an_explicitly_empty_frame_list() -> None:
    """ "The display holds no frames" is a valid, present-and-empty reply."""
    result = FrameStates.from_payload({"frames": []})

    assert isinstance(result, FrameStates)
    assert result.frames == []


def test_from_payload_refuses_a_non_mapping() -> None:
    result = FrameStates.from_payload("not a mapping")

    assert isinstance(result, OpError)
    assert result.code == "fault"


def test_from_payload_refuses_a_reply_missing_the_frames_key() -> None:
    """Regression: a missing "frames" key used to fall back to an empty list,
    silently conflating "no frames" with "reply I don't recognise" -- Copilot
    finding on lux-mxvy.8 / DES-088."""
    result = FrameStates.from_payload({"scenes": []})

    assert isinstance(result, OpError)
    assert result.code == "fault"
    assert "frames" in result.reason


def test_from_payload_refuses_a_malformed_frame_entry() -> None:
    result = FrameStates.from_payload({"frames": [{"frame_id": "f1"}]})

    assert isinstance(result, OpError)
    assert result.code == "fault"


def test_frame_state_is_closed_reflects_visibility() -> None:
    closed = FrameState(frame_id="f1", title="t", visibility="closed", scene_ids=[])
    on_screen = FrameState(
        frame_id="f2", title="t", visibility="on_screen", scene_ids=[]
    )

    assert closed.is_closed is True
    assert on_screen.is_closed is False
