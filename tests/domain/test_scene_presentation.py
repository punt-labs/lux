"""Unit tests for ScenePresentation and its per-scene registry."""

from __future__ import annotations

from punt_lux.domain.hub.frame_ownership import FrameOwnership
from punt_lux.domain.hub.scene_presentation import (
    ScenePresentation,
    ScenePresentationRegistry,
)
from punt_lux.domain.ids import ConnectionId, SceneId
from punt_lux.protocol import SceneMessage


class _RecordingPusher:
    """Capture the one ``send_scene`` call a presentation makes."""

    calls: list[dict[str, object]]

    def __new__(cls) -> _RecordingPusher:
        self = super().__new__(cls)
        self.calls = []
        return self

    def send_scene(self, message: SceneMessage) -> None:
        self.calls.append(
            {
                "scene_id": message.id,
                "elements": message.elements,
                "title": message.title,
                "layout": message.layout,
                "frame_id": message.frame_id,
                "frame_title": message.frame_title,
                "frame_size": message.frame_size,
                "frame_flags": message.frame_flags,
                "frame_layout": message.frame_layout,
                "frame_owner_facts": message.frame_owner_facts,
                "frame_scope_label": message.frame_scope_label,
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
    pres.push(pusher, SceneId("beads"), [], ownership=FrameOwnership())
    (call,) = pusher.calls
    assert call["scene_id"] == "beads"
    assert call["frame_id"] == "board"
    assert call["frame_title"] == "Beads: lux"
    assert call["frame_size"] == (640, 480)
    assert call["frame_flags"] == {"no_resize": True}
    assert call["frame_layout"] == "stack"
    assert call["title"] == "Board"


def test_push_forwards_the_ownership_it_is_given() -> None:
    # Ownership is resolved fresh at send time, never part of the
    # presentation's own persisted fields -- a push-time parameter only.
    pres = ScenePresentation(frame_id="board")
    pusher = _RecordingPusher()
    rows = (("Client", "lux"),)
    pres.push(pusher, SceneId("beads"), [], ownership=FrameOwnership(rows, "lux (2)"))
    (call,) = pusher.calls
    assert call["frame_owner_facts"] == rows
    assert call["frame_scope_label"] == "lux (2)"


def test_push_of_an_unowned_frame_sends_neither_rows_nor_label() -> None:
    pres = ScenePresentation(frame_id="board")
    pusher = _RecordingPusher()
    pres.push(pusher, SceneId("beads"), [], ownership=FrameOwnership())
    (call,) = pusher.calls
    assert call["frame_owner_facts"] is None
    assert call["frame_scope_label"] is None


def test_the_presentation_persists_no_ownership_field() -> None:
    assert "ownership" not in ScenePresentation.__dataclass_fields__
    assert "frame_scope_label" not in ScenePresentation.__dataclass_fields__


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


def test_scenes_in_frame_lists_them_in_the_order_they_entered() -> None:
    registry = ScenePresentationRegistry()
    registry.record(SceneId("s1"), ScenePresentation(frame_id="f"))
    registry.record(SceneId("s2"), ScenePresentation(frame_id="f"))

    assert registry.scenes_in_frame("f") == [SceneId("s1"), SceneId("s2")]


def test_a_scene_moved_into_a_frame_enters_at_its_end() -> None:
    # s1 was recorded first overall, but it enters "shared" after s2 did.
    registry = ScenePresentationRegistry()
    registry.record(SceneId("s1"), ScenePresentation(frame_id="a"))
    registry.record(SceneId("s2"), ScenePresentation(frame_id="shared"))
    registry.record(SceneId("s1"), ScenePresentation(frame_id="shared"))

    assert registry.scenes_in_frame("shared") == [SceneId("s2"), SceneId("s1")]


def test_a_scene_re_shown_in_its_own_frame_keeps_its_place() -> None:
    registry = ScenePresentationRegistry()
    registry.record(SceneId("s1"), ScenePresentation(frame_id="f"))
    registry.record(SceneId("s2"), ScenePresentation(frame_id="f"))
    registry.record(SceneId("s1"), ScenePresentation(frame_id="f", title="again"))

    assert registry.scenes_in_frame("f") == [SceneId("s1"), SceneId("s2")]


def test_a_forgotten_scene_shown_again_enters_at_the_end() -> None:
    registry = ScenePresentationRegistry()
    registry.record(SceneId("s1"), ScenePresentation(frame_id="f"))
    registry.record(SceneId("s2"), ScenePresentation(frame_id="f"))
    registry.forget(SceneId("s1"))
    registry.record(SceneId("s1"), ScenePresentation(frame_id="f"))

    assert registry.scenes_in_frame("f") == [SceneId("s2"), SceneId("s1")]


class TestMessage:
    """The presentation builds the whole-scene wire message; no sender does."""

    def test_carries_every_presentation_field(self) -> None:
        pres = ScenePresentation(
            frame_id="board",
            title="Board",
            layout="rows",
            frame_title="Beads: lux",
            frame_size=(640, 480),
            frame_flags={"no_resize": True},
            frame_layout="stack",
        )

        message = pres.message(SceneId("beads"), [])

        assert (message.id, message.frame_id, message.title) == (
            "beads",
            "board",
            "Board",
        )
        assert (message.layout, message.frame_title) == ("rows", "Beads: lux")
        assert (message.frame_size, message.frame_layout) == ((640, 480), "stack")
        assert message.frame_flags == {"no_resize": True}

    def test_defaults_to_an_unowned_frame(self) -> None:
        message = ScenePresentation(frame_id="board").message("s", [])

        assert message.frame_owner_facts is None
        assert message.frame_scope_label is None

    def test_carries_the_ownership_it_is_given(self) -> None:
        rows = (("Client", "lux"),)

        message = ScenePresentation(frame_id="board").message(
            "s", [], FrameOwnership(rows, "lux (2)")
        )

        assert message.frame_owner_facts == rows
        assert message.frame_scope_label == "lux (2)"

    def test_copies_the_flags_so_the_wire_never_aliases_the_presentation(
        self,
    ) -> None:
        flags = {"no_resize": True}
        message = ScenePresentation(frame_id="board", frame_flags=flags).message(
            "s", []
        )

        assert message.frame_flags == flags
        assert message.frame_flags is not flags

    def test_a_blank_scene_has_no_elements(self) -> None:
        assert ScenePresentation(frame_id="board").message("s", []).elements == []
