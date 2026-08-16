"""SceneSubmission.scoped — composing scene and frame ids together, one owner."""

from __future__ import annotations

from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.operations.scene_submission import SceneSubmission
from punt_lux.protocol import CollapsingHeaderElement

_OWNER = ConnectionId("session-a")


def _submission(scene_id: str, presentation: ScenePresentation) -> SceneSubmission:
    return SceneSubmission.of(
        [CollapsingHeaderElement(id="hdr", label="Details", open=False)],
        scene_id,
        presentation,
        None,
    )


def test_scoped_composes_the_scene_id_against_the_owner() -> None:
    submission = _submission("music-player", ScenePresentation(frame_id="board"))
    scoped = submission.scoped(_OWNER)
    assert scoped.scene_id == SceneId("session-a\x1fmusic-player")


def test_scoped_composes_an_explicit_frame_id_against_the_same_owner() -> None:
    submission = _submission("music-player", ScenePresentation(frame_id="board"))
    scoped = submission.scoped(_OWNER)
    assert scoped.presentation.frame_id == "session-a\x1fboard"


def test_scoped_preserves_the_default_frame_equals_scene_invariant() -> None:
    # A scene shown with no explicit frame_id defaults frame_id to the raw
    # scene_id (RenderRequest.presentation). Composing each independently
    # from its own raw value, against the same owner, must still yield
    # frame_id == scene_id after composition.
    submission = _submission("music-player", ScenePresentation(frame_id="music-player"))
    scoped = submission.scoped(_OWNER)
    assert str(scoped.scene_id) == scoped.presentation.frame_id


def test_scoped_leaves_the_elements_and_ttl_untouched() -> None:
    submission = _submission("music-player", ScenePresentation(frame_id="board"))
    scoped = submission.scoped(_OWNER)
    assert scoped.elements == submission.elements
    assert scoped.ttl_seconds == submission.ttl_seconds
