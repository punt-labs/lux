"""SceneOperations against a real HubDisplay, factory, and recording replicator."""

from __future__ import annotations

from collections.abc import Mapping

from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.hub_factory import hub_element_factory
from punt_lux.domain.hub.quarantine_record import QuarantineRecord
from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.domain.ids import ConnectionId, ElementId, SceneId, Topic
from punt_lux.operations import (
    Cleared,
    OpError,
    RenderRequest,
    SceneShown,
    UpdateRequest,
)
from punt_lux.operations.scene_installer import SceneInstaller
from punt_lux.operations.scene_submission import SceneSubmission
from punt_lux.operations.scenes import SceneOperations
from punt_lux.operations.scope import Scope
from punt_lux.protocol import CollapsingHeaderElement

_LOCAL = Scope(ConnectionId("local"))


class _Recorder:
    """Records the replicator signals an operation sends."""

    def __init__(self) -> None:
        self.dirtied: list[SceneId] = []

    def mark_dirty(self, scene_id: SceneId) -> None:
        self.dirtied.append(scene_id)

    def mark_menus(self) -> None:
        """Unused here — scene operations never mark the menu bar."""


def _ops(
    store: HubDisplay, recorder: _Recorder, hub: Hub | None = None
) -> SceneOperations:
    return SceneOperations(store, recorder, hub_element_factory, hub or Hub())


def _submitted(scene_id: str) -> SceneSubmission:
    """One header root offered as a permanent scene framed by its own id."""
    return SceneSubmission.of(
        [CollapsingHeaderElement(id="hdr", label="Details", open=False)],
        scene_id,
        ScenePresentation(frame_id=scene_id),
        None,
    )


def _seed_header(store: HubDisplay, *, is_open: bool = False) -> None:
    store.replace_scene(
        ConnectionId("local"),
        SceneId("s1"),
        [CollapsingHeaderElement(id="hdr", label="Details", open=is_open)],
    )


def test_render_installs_scene_and_marks_dirty() -> None:
    store, recorder = HubDisplay(), _Recorder()
    request = RenderRequest.parse(
        {"scene_id": "s1", "elements": [{"kind": "text", "id": "t1", "content": "Hi"}]}
    )
    result = _ops(store, recorder).render(request, scope=_LOCAL)
    assert isinstance(result, SceneShown)
    assert result.scene_id == "s1"
    assert recorder.dirtied == [SceneId("s1")]
    assert store.resolve(SceneId("s1"), ElementId("t1")).id == "t1"


def test_render_without_a_frame_synthesizes_one_at_the_scene_id() -> None:
    # THE RULE at the operations path: a frameless request installs a scene whose
    # recorded presentation frames it by its own id — no scene reaches the store
    # unframed. All three surfaces (MCP show, REST PUT, CLI) inherit this here.
    store, recorder = HubDisplay(), _Recorder()
    request = RenderRequest.parse(
        {"scene_id": "s1", "elements": [{"kind": "text", "id": "t1", "content": "Hi"}]}
    )
    result = _ops(store, recorder).render(request, scope=_LOCAL)
    assert isinstance(result, SceneShown)
    presentation = store.frames.presentation_for(SceneId("s1"))
    assert presentation.frame_id == "s1"
    assert presentation.frame_title == "s1"


def test_synthesized_frame_is_a_lifecycle_citizen_a_close_removes_the_scene() -> None:
    # The synthesized frame participates in the dismissal machinery identically to
    # an explicit one: closing frame "s1" tears down the scene's roots on the Hub.
    store, recorder = HubDisplay(), _Recorder()
    request = RenderRequest.parse(
        {"scene_id": "s1", "elements": [{"kind": "text", "id": "t1", "content": "Hi"}]}
    )
    _ops(store, recorder).render(request, scope=_LOCAL)
    removed = store.frames.remove_frame("s1")
    assert removed == frozenset({SceneId("s1")})
    assert store.scene_roots(SceneId("s1")) == []


def test_a_frameless_request_arms_no_ttl_the_synthesized_frame_is_permanent() -> None:
    # A TTL rides in on the frame spec; a request that names no frame has no TTL
    # to arm, so its synthesized frame is permanent by construction.
    request = RenderRequest.parse(
        {"scene_id": "s1", "elements": [{"kind": "text", "id": "t1", "content": "Hi"}]}
    )
    assert isinstance(request, RenderRequest)
    assert request.frame_ttl() is None


def test_render_passes_an_op_error_straight_through() -> None:
    recorder = _Recorder()
    error = OpError(code="invalid_request", reason="bad layout")
    result = _ops(HubDisplay(), recorder).render(error, scope=_LOCAL)
    assert result is error
    assert recorder.dirtied == []


def test_render_rejects_a_duplicate_id_and_installs_nothing() -> None:
    store, recorder = HubDisplay(), _Recorder()
    request = RenderRequest.parse(
        {
            "scene_id": "s1",
            "elements": [
                {"kind": "text", "id": "dup", "content": "a"},
                {"kind": "text", "id": "dup", "content": "b"},
            ],
        }
    )
    result = _ops(store, recorder).render(request, scope=_LOCAL)
    assert isinstance(result, OpError)
    assert result.code == "rejected"
    # The reason is bare — no "scene not rendered — " prefix; that is the adapter's.
    assert "duplicate" in result.reason
    assert recorder.dirtied == []


def test_render_rejects_an_undecodable_element_without_raising() -> None:
    store, recorder = HubDisplay(), _Recorder()
    request = RenderRequest.parse(
        {"scene_id": "s1", "elements": [{"kind": "text", "id": "t1"}]}
    )
    result = _ops(store, recorder).render(request, scope=_LOCAL)
    assert isinstance(result, OpError)
    assert result.code == "rejected"
    assert recorder.dirtied == []


def test_render_rejects_a_type_error_wire_shape_without_raising() -> None:
    # A wrong-typed wire shape raises TypeError (not ValueError) in the codec —
    # here a table's ``handlers`` that is not a list. The decode boundary must
    # catch it too, so show() returns a rejection, not a traceback/500.
    store, recorder = HubDisplay(), _Recorder()
    request = RenderRequest.parse(
        {
            "scene_id": "s1",
            "elements": [
                {
                    "kind": "table",
                    "id": "t1",
                    "columns": ["A"],
                    "rows": [["x"]],
                    "handlers": "not-a-list",
                }
            ],
        }
    )
    result = _ops(store, recorder).render(request, scope=_LOCAL)
    assert isinstance(result, OpError)
    assert result.code == "rejected"
    assert "handlers" in result.reason
    assert recorder.dirtied == []


def test_render_rejects_a_legacy_missing_id_without_raising() -> None:
    # A legacy dataclass decoder indexes required fields directly (d["id"]), so a
    # legacy-only wire (a paged group) missing id raises KeyError, not ValueError.
    # The decode boundary must catch it too, or malformed input becomes a 500.
    store, recorder = HubDisplay(), _Recorder()
    request = RenderRequest.parse(
        {"scene_id": "s1", "elements": [{"kind": "group", "layout": "paged"}]}
    )
    result = _ops(store, recorder).render(request, scope=_LOCAL)
    assert isinstance(result, OpError)
    assert result.code == "rejected"
    assert recorder.dirtied == []


def test_update_sets_a_field_and_marks_dirty() -> None:
    store, recorder = HubDisplay(), _Recorder()
    _seed_header(store, is_open=False)
    request = UpdateRequest.parse([{"id": "hdr", "set": {"open": True}}])
    result = _ops(store, recorder).update("s1", request, scope=_LOCAL)
    assert isinstance(result, SceneShown)
    header = store.resolve(SceneId("s1"), ElementId("hdr"))
    assert isinstance(header, CollapsingHeaderElement)
    assert header.open is True
    assert recorder.dirtied == [SceneId("s1")]


def test_update_rejects_an_unknown_element_and_leaves_the_store_untouched() -> None:
    store, recorder = HubDisplay(), _Recorder()
    _seed_header(store)
    request = UpdateRequest.parse([{"id": "ghost", "set": {"open": True}}])
    result = _ops(store, recorder).update("s1", request, scope=_LOCAL)
    assert isinstance(result, OpError)
    assert result.code == "rejected"
    # The reason is bare — the writer names the element; the adapter adds the prefix.
    assert "ghost" in result.reason
    assert recorder.dirtied == []
    assert store.resolve(SceneId("s1"), ElementId("hdr")).id == "hdr"


def test_clear_empties_every_owned_scene_and_marks_each_dirty() -> None:
    # No-arg clear empties all the caller's scenes and marks each one dirty so the
    # replicator blanks each into its own frame — never a whole-display blank, which
    # would empty the Display while the Hub still held other owners' scenes.
    store, recorder = HubDisplay(), _Recorder()
    _seed_header(store)
    store.replace_scene(
        ConnectionId("local"),
        SceneId("s2"),
        [CollapsingHeaderElement(id="hdr2", label="More", open=False)],
    )
    _ops(store, recorder).clear(scope=_LOCAL)
    assert store.scene_roots(SceneId("s1")) == []
    assert store.scene_roots(SceneId("s2")) == []
    assert set(recorder.dirtied) == {SceneId("s1"), SceneId("s2")}


def test_scene_scoped_clear_empties_only_the_named_scene() -> None:
    # clear(scene_id="s1") removes only that scene's roots and dirties only it; the
    # caller's other scene stays installed and is never marked for a blank.
    store, recorder = HubDisplay(), _Recorder()
    _seed_header(store)
    store.replace_scene(
        ConnectionId("local"),
        SceneId("s2"),
        [CollapsingHeaderElement(id="hdr2", label="More", open=False)],
    )
    result = _ops(store, recorder).clear(scope=_LOCAL, scene_id="s1")
    assert isinstance(result, Cleared)
    assert store.scene_roots(SceneId("s1")) == []
    assert store.resolve(SceneId("s2"), ElementId("hdr2")).id == "hdr2"
    assert recorder.dirtied == [SceneId("s1")]


def test_scene_scoped_clear_of_an_unknown_scene_is_not_found() -> None:
    # A scene-scoped clear that removes nothing must not lie "cleared": an id no
    # scene holds is not_found — the same verdict inspect_scene returns for it.
    store, recorder = HubDisplay(), _Recorder()
    result = _ops(store, recorder).clear(scope=_LOCAL, scene_id="ghost")
    assert isinstance(result, OpError)
    assert result.code == "not_found"
    assert recorder.dirtied == []


def test_scene_scoped_clear_of_an_unowned_scene_is_rejected() -> None:
    # A real scene the caller owns nothing in is a rejection, not a false success,
    # and the other owner's roots are left untouched.
    store, recorder = HubDisplay(), _Recorder()
    store.replace_scene(
        ConnectionId("agent-b"),
        SceneId("theirs"),
        [CollapsingHeaderElement(id="x", label="X", open=False)],
    )
    result = _ops(store, recorder).clear(scope=_LOCAL, scene_id="theirs")
    assert isinstance(result, OpError)
    assert result.code == "rejected"
    assert store.resolve(SceneId("theirs"), ElementId("x")).id == "x"
    assert recorder.dirtied == []


class TestWhoAnInstallRegisters:
    """A caller showing a scene is a client; a client written *for* is not."""

    def test_the_callers_own_install_registers_it(self) -> None:
        # A client that only ever shows still appears among the Hub's clients:
        # its show is its contact, and there may never be another kind.
        store, recorder = HubDisplay(), _Recorder()
        request = RenderRequest.parse(
            {
                "scene_id": "s1",
                "elements": [{"kind": "text", "id": "t1", "content": "Hi"}],
            }
        )
        result = _ops(store, recorder).render(request, scope=_LOCAL)
        assert isinstance(result, SceneShown)
        assert [str(c) for c in store.client_sessions()] == ["local"]

    def test_a_scene_written_for_a_departed_client_does_not_recreate_it(self) -> None:
        # The ghost: the Hub writes a per-client scene for a connection that has
        # gone since the read that named it. Attribution is not contact — the
        # install must leave the registry as the departure left it.
        store, recorder = HubDisplay(), _Recorder()
        departed = ConnectionId("gone")
        store.register_client(departed)
        store.drop_connection(departed)

        result = SceneInstaller(store, recorder).install(
            _submitted("lux.client-details.gone"), owner=departed
        )

        assert isinstance(result, SceneShown)
        assert dict(store.client_sessions()) == {}

    def test_a_scene_written_for_an_unknown_client_registers_nobody(self) -> None:
        # The same rule where no session ever existed: nothing the Hub writes on a
        # connection's behalf may invent one.
        store, recorder = HubDisplay(), _Recorder()
        SceneInstaller(store, recorder).install(
            _submitted("lux.client-details.never"), owner=ConnectionId("never")
        )
        assert dict(store.client_sessions()) == {}


def test_scene_scoped_clear_preserves_a_custom_frame_binding() -> None:
    # A scene shown in a custom frame keeps its presentation through clear: the
    # writer no longer forgets the frame, so the replicator's empty-push blanks the
    # frame the scene was actually shown in, not one guessed from the scene id.
    store, recorder = HubDisplay(), _Recorder()
    store.show_scene(
        ConnectionId("local"),
        SceneId("board"),
        [CollapsingHeaderElement(id="hdr", label="Board", open=False)],
        ScenePresentation(frame_id="beads-lux"),
        ttl_seconds=None,
    )
    _ops(store, recorder).clear(scope=_LOCAL, scene_id="board")
    assert store.scene_roots(SceneId("board")) == []
    assert store.frames.presentation_for(SceneId("board")).frame_id == "beads-lux"


class TestQuarantinedScenes:
    """A patch-style update against a quarantined scene is refused, not applied."""

    def test_update_against_a_quarantined_scene_is_rejected(self) -> None:
        store, recorder = HubDisplay(), _Recorder()
        _seed_header(store)
        store.quarantine(
            SceneId("s1"),
            QuarantineRecord(death_count=2, last_death_at=123.0),
        )
        request = UpdateRequest.parse([{"id": "hdr", "set": {"open": True}}])
        result = _ops(store, recorder).update("s1", request, scope=_LOCAL)
        assert isinstance(result, OpError)
        assert result.code == "rejected"
        assert "quarantined" in result.reason
        assert recorder.dirtied == []

    def test_update_against_a_quarantined_scene_leaves_the_store_untouched(
        self,
    ) -> None:
        store, recorder = HubDisplay(), _Recorder()
        _seed_header(store, is_open=False)
        store.quarantine(
            SceneId("s1"),
            QuarantineRecord(death_count=2, last_death_at=123.0),
        )
        request = UpdateRequest.parse([{"id": "hdr", "set": {"open": True}}])
        _ops(store, recorder).update("s1", request, scope=_LOCAL)
        header = store.resolve(SceneId("s1"), ElementId("hdr"))
        assert isinstance(header, CollapsingHeaderElement)
        assert header.open is False  # the patch never applied

    def test_update_against_a_quarantined_scene_publishes_to_the_callers_topic(
        self,
    ) -> None:
        # The push half of the two reach paths: an agent subscribed to its own
        # scene's topic learns even though it is the one whose write triggered
        # the discovery, proving the publish fired at all.
        store, recorder = HubDisplay(), _Recorder()
        _seed_header(store)
        store.quarantine(
            SceneId("s1"),
            QuarantineRecord(death_count=2, last_death_at=123.0, render_error="boom"),
        )
        hub = Hub()
        received: list[Mapping[str, object]] = []
        hub.register_writer(
            _LOCAL.connection_id, lambda msg: received.append(msg.payload)
        )
        hub.subscribe(_LOCAL.connection_id, Topic("scene:s1:quarantined"))
        request = UpdateRequest.parse([{"id": "hdr", "set": {"open": True}}])
        _ops(store, recorder, hub).update("s1", request, scope=_LOCAL)
        assert received == [
            {
                "status": "quarantined",
                "death_count": 2,
                "last_death_at": 123.0,
                "render_error": "boom",
            }
        ]

    def test_a_wholesale_render_lifts_the_quarantine(self) -> None:
        # The recovery path: a full replace is a different tree, presumed
        # fixed, and it is not gated the way a patch is.
        store, recorder = HubDisplay(), _Recorder()
        _seed_header(store)
        store.quarantine(
            SceneId("s1"),
            QuarantineRecord(death_count=2, last_death_at=123.0),
        )
        request = RenderRequest.parse(
            {
                "scene_id": "s1",
                "elements": [{"kind": "text", "id": "t1", "content": "fixed"}],
            }
        )
        result = _ops(store, recorder).render(request, scope=_LOCAL)
        assert isinstance(result, SceneShown)
        assert not store.is_quarantined(SceneId("s1"))
        assert recorder.dirtied == [SceneId("s1")]

    def test_scene_scoped_clear_of_a_quarantined_scene_lifts_the_quarantine(
        self,
    ) -> None:
        # Test-gap 9: clear() on a quarantined scene must leave the store with
        # neither roots nor a quarantine record — a scene with nothing to render
        # is not "quarantined-and-empty," it is just gone. Otherwise the caller
        # could not re-show later without first hitting a spurious rejection.
        store, recorder = HubDisplay(), _Recorder()
        _seed_header(store)
        store.quarantine(
            SceneId("s1"), QuarantineRecord(death_count=2, last_death_at=1.0)
        )
        result = _ops(store, recorder).clear(scope=_LOCAL, scene_id="s1")
        assert isinstance(result, Cleared)
        assert store.scene_roots(SceneId("s1")) == []
        assert not store.is_quarantined(SceneId("s1"))
        # And re-showing under the same id must succeed, not hit a spurious
        # quarantine rejection.
        request = RenderRequest.parse(
            {
                "scene_id": "s1",
                "elements": [{"kind": "text", "id": "t2", "content": "fresh"}],
            }
        )
        assert isinstance(
            _ops(store, recorder).render(request, scope=_LOCAL), SceneShown
        )
