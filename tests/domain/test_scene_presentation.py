"""Unit tests for ScenePresentation and its per-scene registry."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from punt_lux.domain.hub.scene_presentation import (
    ScenePresentation,
    ScenePresentationRegistry,
)
from punt_lux.domain.ids import ConnectionId, SceneId

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


def test_a_recorded_presentation_persists_for_the_scene_lifetime() -> None:
    # A presentation is kept once recorded and only overwritten by a re-show, so
    # an emptied scene can still be blanked into the frame it was shown in.
    reg = ScenePresentationRegistry()
    reg.record(SceneId("s1"), ScenePresentation(frame_id="custom-frame"))
    assert reg.presentation_for(SceneId("s1")).frame_id == "custom-frame"


def test_forget_drops_a_recorded_presentation() -> None:
    # The replicator calls forget once it blanks an emptied scene away, so the map
    # does not grow for the process lifetime; a later lookup falls back to the
    # self-framed default.
    reg = ScenePresentationRegistry()
    reg.record(SceneId("s1"), ScenePresentation(frame_id="custom-frame"))
    reg.forget(SceneId("s1"))
    assert reg.presentation_for(SceneId("s1")).frame_id == "s1"  # back to default


def test_forget_of_an_unrecorded_scene_is_a_no_op() -> None:
    # Forgetting a never-explicitly-framed scene reclaims nothing and does not
    # raise, so a blank of such a scene is safe.
    reg = ScenePresentationRegistry()
    reg.forget(SceneId("never-recorded"))
    assert reg.presentation_for(SceneId("never-recorded")).frame_id == "never-recorded"


def test_scoped_composes_the_frame_id_against_the_owner() -> None:
    pres = ScenePresentation(frame_id="board")
    scoped = pres.scoped(ConnectionId("session-a"))
    assert scoped.frame_id == "session-a\x1fboard"


def test_scoped_leaves_every_other_field_untouched() -> None:
    pres = ScenePresentation(
        frame_id="board",
        title="Board",
        frame_title="Beads: lux",
        frame_size=(640, 480),
        frame_flags={"no_resize": True},
        frame_layout="stack",
    )
    scoped = pres.scoped(ConnectionId("session-a"))
    assert scoped.title == "Board"
    assert scoped.frame_title == "Beads: lux"
    assert scoped.frame_size == (640, 480)
    assert scoped.frame_flags == {"no_resize": True}
    assert scoped.frame_layout == "stack"


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


def test_frame_id_for_local_resolves_a_recorded_scoped_frame() -> None:
    # This is the read raise_frame needs: a caller names its frame by the
    # plain local id it gave it, resolved within its OWN connection.
    reg = ScenePresentationRegistry()
    scoped = ScenePresentation(frame_id="beads-lux").scoped(ConnectionId("c1"))
    reg.record(SceneId("c1\x1fbeads-lux"), scoped)
    assert (
        reg.frame_id_for_local("beads-lux", connection=ConnectionId("c1"))
        == scoped.frame_id
    )


def test_frame_id_for_local_resolves_again_after_a_forget_and_reshow() -> None:
    # The connection id is a stable function of identity (DES-086), so the
    # same connection re-showing under its own name resolves the same way
    # a fresh lookup would -- no search across other connections needed.
    reg = ScenePresentationRegistry()
    reg.record(
        SceneId("c1\x1fbeads-lux"),
        ScenePresentation(frame_id="beads-lux").scoped(ConnectionId("c1")),
    )
    reg.forget(SceneId("c1\x1fbeads-lux"))
    reshown = ScenePresentation(frame_id="beads-lux").scoped(ConnectionId("c1"))
    reg.record(SceneId("c1\x1fbeads-lux"), reshown)
    assert (
        reg.frame_id_for_local("beads-lux", connection=ConnectionId("c1"))
        == reshown.frame_id
    )


def test_frame_id_for_local_returns_none_for_an_unknown_name() -> None:
    reg = ScenePresentationRegistry()
    assert reg.frame_id_for_local("never-shown", connection=ConnectionId("c1")) is None


def test_frame_id_for_local_is_scoped_to_the_callers_own_connection() -> None:
    # Two connections both named a frame "issues" -- unambiguous by
    # construction, since each connection's own lookup only ever composes
    # its own scoped id and never searches the other's.
    reg = ScenePresentationRegistry()
    reg.record(
        SceneId("c1\x1fissues"),
        ScenePresentation(frame_id="issues").scoped(ConnectionId("c1")),
    )
    reg.record(
        SceneId("c2\x1fissues"),
        ScenePresentation(frame_id="issues").scoped(ConnectionId("c2")),
    )
    assert (
        reg.frame_id_for_local("issues", connection=ConnectionId("c1"))
        == "c1\x1fissues"
    )
    assert (
        reg.frame_id_for_local("issues", connection=ConnectionId("c2"))
        == "c2\x1fissues"
    )
