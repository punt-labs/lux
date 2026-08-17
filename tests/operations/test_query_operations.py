"""QueryOperations — the reach-around removal.

These tests encode the two corrections the one-code-path move lands.
``inspect_scene`` and ``list_scenes`` must answer from ``HubDisplay`` — the
authority — with no display round-trip: the injected port raises if touched, so a
passing read proves it never reached around to the display. ``list_clients`` must
answer from the Hub session registry, not the display's socket-client list.
``list_recent_events`` and ``list_errors`` are display facts, so they DO proxy.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Self, cast

from punt_lux.domain.element import Element as DomainElement
from punt_lux.domain.hub.connection_scoped_id import ConnectionScopedId
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.quarantine_record import QuarantineRecord
from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.domain.ids import ConnectionId, SceneId, Topic
from punt_lux.domain.update import AddElement
from punt_lux.operations.display_reply import DisplayFault, DisplayReplied, DisplayReply
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.inspect_scope import InspectScope
from punt_lux.operations.models.query_clients import ClientList
from punt_lux.operations.models.query_errors import RecentErrors
from punt_lux.operations.models.query_events import RecentEvents
from punt_lux.operations.models.query_geometry import GeometryPresent
from punt_lux.operations.models.query_inspection import SceneInspection
from punt_lux.operations.models.query_scenes import SceneList
from punt_lux.operations.queries import QueryOperations
from punt_lux.operations.scope import Scope
from punt_lux.protocol.agent_factory import agent_element_factory

if TYPE_CHECKING:
    import pytest


def _scoped(connection: str, local_id: str) -> SceneId:
    """The store key ``local_id`` composes to for ``connection``."""
    return SceneId(ConnectionScopedId.compose(ConnectionId(connection), local_id))


_C1 = Scope(ConnectionId("c1"))


class _ForbiddenPort:
    """A DisplayPort that fails the test if any proxied call is made.

    Injected into the Hub-authoritative reads to prove they never reach around
    to the display.
    """

    def query(self, method: str, params: Mapping[str, object]) -> DisplayReply:
        msg = f"Hub read reached around to the display: query({method!r})"
        raise AssertionError(msg)

    def ping(self, wait: float | None) -> DisplayReply:
        msg = f"Hub read reached around to the display: ping({wait!r})"
        raise AssertionError(msg)


class _StubPort:
    """A DisplayPort returning a preset reply for the proxied reads."""

    _reply: DisplayReply

    def __new__(cls, reply: DisplayReply) -> Self:
        self = super().__new__(cls)
        self._reply = reply
        return self

    def query(self, method: str, params: Mapping[str, object]) -> DisplayReply:
        return self._reply

    def ping(self, wait: float | None) -> DisplayReply:
        return self._reply


class _CountingPort:
    """A DisplayPort that records each query so a test can assert the count."""

    _reply: DisplayReply
    calls: list[tuple[str, Mapping[str, object]]]
    __slots__ = ("_reply", "calls")

    def __new__(cls, reply: DisplayReply) -> Self:
        self = super().__new__(cls)
        self._reply = reply
        self.calls = []
        return self

    def query(self, method: str, params: Mapping[str, object]) -> DisplayReply:
        self.calls.append((method, params))
        return self._reply

    def ping(self, wait: float | None) -> DisplayReply:
        return self._reply


def _seed_scene(store: HubDisplay, *, scene: str, connection: str) -> None:
    """Install a group root with a text child under one connection.

    The connection registers itself first, as a client showing a scene does: a
    store write is attribution, never an arrival, so writing alone would leave
    the scene owned by a connection the Hub holds no session for. Seeded at
    the composed key a real show() would produce, so a caller-scoped
    inspect_scene(scene, scope=Scope(connection)) finds it (DES-086).
    """
    store.register_client(ConnectionId(connection))
    group = agent_element_factory().element_from_dict(
        {
            "kind": "group",
            "id": "g1",
            "children": [{"kind": "text", "id": "t1", "content": "hi"}],
        }
    )
    store.show_scene(
        ConnectionId(connection),
        _scoped(connection, scene),
        [cast("DomainElement", group)],
        ScenePresentation(frame_id="frame-a", frame_title="Frame A", layout="single"),
    )


def test_local_id_of_returns_the_callers_own_name_for_a_composed_key() -> None:
    composed = _scoped("session-a", "music-player")
    assert QueryOperations.local_id_of(composed) == "music-player"


def test_local_id_of_falls_back_to_the_raw_key_when_not_composed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # A key installed through a lower-level API outside the composition choke
    # point carries no separator at all — the fallback reports it as-is rather
    # than raising, but the anomaly is logged, not silently absorbed (M-A).
    with caplog.at_level("WARNING"):
        assert QueryOperations.local_id_of("board") == "board"
    assert "non-composed store key" in caplog.text
    assert "'board'" in caplog.text


def test_inspect_scene_reads_the_hub_without_touching_the_display() -> None:
    store = HubDisplay()
    _seed_scene(store, scene="s1", connection="c1")
    ops = QueryOperations(store, Hub(), _ForbiddenPort())

    result = ops.inspect_scene("s1", _C1)

    assert isinstance(result, SceneInspection)
    assert result.scene_id == "s1"
    root = result.elements[0]
    assert root.id == "g1"
    assert root.children[0].id == "t1"


def test_inspect_scene_geometry_round_trips_when_requested() -> None:
    store = HubDisplay()
    _seed_scene(store, scene="s1", connection="c1")  # g1 + t1 = two elements
    reply = DisplayReplied(
        {
            "scene_id": "s1",
            "geometry": {
                "elements": {
                    "t1": {
                        "rect": {"x": 8.0, "y": 8.0, "width": 120.0, "height": 18.0},
                        "paint_sequence": 0,
                        "stack_index": 2,
                    }
                },
                "anonymous": {},
                "frame": {
                    "rect": {"x": 0.0, "y": 0.0, "width": 640.0, "height": 480.0},
                    "stack_index": 0,
                },
            },
        }
    )
    port = _CountingPort(reply)
    ops = QueryOperations(store, Hub(), port)

    result = ops.inspect_scene("s1", _C1, InspectScope(want_geometry=True))

    assert isinstance(result, SceneInspection)
    assert len(port.calls) == 1
    assert port.calls[0][1].get("want_geometry") is True
    assert isinstance(result.geometry, GeometryPresent)
    assert result.geometry.elements["t1"].rect.width == 120.0


def test_inspect_scene_geometry_not_requested_issues_zero_queries() -> None:
    # A bare scope wanting neither fact issues no round-trip at all.
    store = HubDisplay()
    _seed_scene(store, scene="s1", connection="c1")
    ops = QueryOperations(store, Hub(), _ForbiddenPort())

    result = ops.inspect_scene("s1", _C1)

    assert isinstance(result, SceneInspection)


def test_inspect_scene_unknown_scene_is_not_found() -> None:
    ops = QueryOperations(HubDisplay(), Hub(), _ForbiddenPort())
    result = ops.inspect_scene("ghost", _C1)
    assert isinstance(result, OpError)
    assert result.code == "not_found"


def test_inspect_scene_cannot_read_another_connections_scene() -> None:
    # DES-086 Decision 5, operator-narrowed: "you can only inspect what you
    # put into the hub/display." B's "s1" must never answer A's read — not
    # distinguished from an unknown scene, and no fallback lookup may
    # silently resolve it for a connection that never wrote it.
    store = HubDisplay()
    _seed_scene(store, scene="s1", connection="b")
    ops = QueryOperations(store, Hub(), _ForbiddenPort())

    result = ops.inspect_scene("s1", Scope(ConnectionId("a")))

    assert isinstance(result, OpError)
    assert result.code == "not_found"


def test_inspect_scene_with_a_blank_scene_id_is_rejected_before_composition() -> None:
    ops = QueryOperations(HubDisplay(), Hub(), _ForbiddenPort())
    result = ops.inspect_scene("", _C1)
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"


def test_inspect_scene_with_a_separator_in_the_id_is_rejected() -> None:
    ops = QueryOperations(HubDisplay(), Hub(), _ForbiddenPort())
    result = ops.inspect_scene("foo\x1fbar", _C1)
    assert isinstance(result, OpError)
    assert result.code == "invalid_request"


def test_inspect_scene_a_live_scene_carries_no_quarantine_info() -> None:
    store = HubDisplay()
    _seed_scene(store, scene="s1", connection="c1")
    ops = QueryOperations(store, Hub(), _ForbiddenPort())

    result = ops.inspect_scene("s1", _C1)

    assert isinstance(result, SceneInspection)
    assert result.quarantine is None


def test_inspect_scene_a_quarantined_scene_stays_inspectable() -> None:
    # The store keeps a quarantined scene for inspection — quarantine is a
    # replication decision, not a deletion.
    store = HubDisplay()
    _seed_scene(store, scene="s1", connection="c1")
    store.quarantine(
        _scoped("c1", "s1"),
        QuarantineRecord(death_count=2, last_death_at=42.0, render_error="boom"),
    )
    ops = QueryOperations(store, Hub(), _ForbiddenPort())

    result = ops.inspect_scene("s1", _C1)

    assert isinstance(result, SceneInspection)
    assert result.elements  # the tree is still there
    assert result.quarantine is not None
    assert result.quarantine.death_count == 2
    assert result.quarantine.last_death_at == 42.0
    assert result.quarantine.render_error == "boom"


def test_list_scenes_reads_the_hub_without_touching_the_display() -> None:
    store = HubDisplay()
    _seed_scene(store, scene="s1", connection="c1")
    ops = QueryOperations(store, Hub(), _ForbiddenPort())

    result = ops.list_scenes()

    assert isinstance(result, SceneList)
    summary = next(s for s in result.scenes if s.local_id == "s1")
    assert summary.scene_id == str(_scoped("c1", "s1"))
    assert summary.element_count == 2  # the group and its text child
    assert summary.frame_id == "frame-a"
    # A single-owner scene lists the one owner; unidentified here, so the
    # connection is the only handle and no identity is declared.
    assert [o.connection_id for o in summary.owners] == ["c1"]
    assert summary.owners[0].identity is None
    frame = next(f for f in result.frames if f.frame_id == "frame-a")
    assert frame.scene_ids == [str(_scoped("c1", "s1"))]
    assert frame.layout == "tab"  # no explicit frame layout defaults to tab


def test_list_scenes_lists_every_owning_connection_of_a_shared_scene() -> None:
    # Two sessions each install a root into one scene; the summary names both, in
    # first-appearance order — reporting only the first root's owner (the old
    # singular field) could name the wrong session.
    store = HubDisplay()
    _seed_scene(store, scene="s1", connection="c1")  # c1 owns root g1
    second_root = agent_element_factory().element_from_dict(
        {"kind": "text", "id": "t2", "content": "from c2"}
    )
    store.apply(
        ConnectionId("c2"),
        AddElement(
            scene_id=_scoped("c1", "s1"),
            parent_id=None,
            element=cast("DomainElement", second_root),
        ),
    )
    ops = QueryOperations(store, Hub(), _ForbiddenPort())

    summary = next(s for s in ops.list_scenes().scenes if s.local_id == "s1")
    assert [o.connection_id for o in summary.owners] == ["c1", "c2"]


def test_list_scenes_surfaces_the_owner_declared_identity() -> None:
    # A session that declared its identity before installing is attributed by
    # that identity — kind, name, repo — not just its opaque connection id.
    from punt_lux.domain.hub.client_identity import ClientIdentity

    store = HubDisplay()
    identity = ClientIdentity(kind="cli", name="lux", repo="/w/lux")
    store.identify_client(ConnectionId("c1"), identity)
    _seed_scene(store, scene="s1", connection="c1")
    ops = QueryOperations(store, Hub(), _ForbiddenPort())

    summary = next(s for s in ops.list_scenes().scenes if s.local_id == "s1")
    assert summary.owners[0].connection_id == "c1"
    assert summary.owners[0].identity == identity  # structured attribution


def test_list_scenes_reports_live_status_by_default() -> None:
    store = HubDisplay()
    _seed_scene(store, scene="s1", connection="c1")
    ops = QueryOperations(store, Hub(), _ForbiddenPort())

    summary = next(s for s in ops.list_scenes().scenes if s.local_id == "s1")
    assert summary.status == "live"
    assert summary.quarantine is None


def test_list_scenes_reports_a_quarantined_scene() -> None:
    store = HubDisplay()
    _seed_scene(store, scene="s1", connection="c1")
    store.quarantine(
        _scoped("c1", "s1"), QuarantineRecord(death_count=2, last_death_at=99.0)
    )
    ops = QueryOperations(store, Hub(), _ForbiddenPort())

    summary = next(s for s in ops.list_scenes().scenes if s.local_id == "s1")
    assert summary.status == "quarantined"
    assert summary.quarantine is not None
    assert summary.quarantine.death_count == 2
    assert summary.quarantine.last_death_at == 99.0


def test_list_clients_reads_the_hub_session_registry() -> None:
    store = HubDisplay()
    _seed_scene(store, scene="s1", connection="c1")
    hub = Hub()
    hub.register_writer(ConnectionId("c1"), lambda _msg: None)
    hub.subscribe(ConnectionId("c1"), Topic("work.saved"))
    ops = QueryOperations(store, hub, _ForbiddenPort())

    result = ops.list_clients()

    assert isinstance(result, ClientList)
    client = next(c for c in result.clients if c.connection_id == "c1")
    assert client.subscribed_topics == ["work.saved"]
    # owned_scenes reports the caller's own local id, not the composed store
    # key — the same shape inspect_scene/update/clear accept back, so an
    # agent can round-trip a value straight from list_clients into those
    # calls without separator rejection (Bugbot M, DES-086).
    assert client.owned_scenes == ["s1"]
    # Age is read from the same monotonic clock the session was stamped with, so
    # it is a coherent, non-negative float — never negative from a wall-clock step.
    assert isinstance(client.connected_seconds, float)
    assert client.connected_seconds >= 0.0


def test_list_clients_owned_scenes_round_trips_into_inspect_scene() -> None:
    # The exact regression Bugbot flagged: an agent discovers a scene via
    # list_clients, then feeds that string straight back into inspect_scene.
    # A composed key here would separator-reject; a local id succeeds.
    store = HubDisplay()
    _seed_scene(store, scene="foo", connection="c1")
    hub = Hub()
    hub.register_writer(ConnectionId("c1"), lambda _msg: None)
    ops = QueryOperations(store, hub, _ForbiddenPort())

    client = next(c for c in ops.list_clients().clients if c.connection_id == "c1")
    discovered = client.owned_scenes[0]
    assert discovered == "foo"

    result = ops.inspect_scene(discovered, Scope(ConnectionId("c1")))

    assert isinstance(result, SceneInspection)


def test_list_clients_owned_scenes_reports_two_connections_separately() -> None:
    store = HubDisplay()
    _seed_scene(store, scene="foo", connection="c1")
    _seed_scene(store, scene="foo", connection="c2")
    hub = Hub()
    hub.register_writer(ConnectionId("c1"), lambda _msg: None)
    hub.register_writer(ConnectionId("c2"), lambda _msg: None)
    ops = QueryOperations(store, hub, _ForbiddenPort())

    clients = {c.connection_id: c for c in ops.list_clients().clients}

    assert clients["c1"].owned_scenes == ["foo"]
    assert clients["c2"].owned_scenes == ["foo"]


def test_list_recent_events_proxies_the_display() -> None:
    payload = {
        "events": [
            {
                "element_id": "btn-go",
                "action": "click",
                "event_kind": "button_clicked",
                "value": True,
                "timestamp": 1000.0,
            }
        ],
        "total_buffered": 1,
    }
    ops = QueryOperations(HubDisplay(), Hub(), _StubPort(DisplayReplied(payload)))
    result = ops.list_recent_events(50)
    assert isinstance(result, RecentEvents)
    assert result.events[0].element_id == "btn-go"
    # event_kind is carried through, not dropped — it names the event type the
    # display recorded (button_clicked, value_changed, ...).
    assert result.events[0].event_kind == "button_clicked"
    assert result.total_buffered == 1


def test_list_errors_accepts_the_live_display_payload() -> None:
    # Guards the same drift the get_display_info fix guards: the display's real
    # error shape must validate against the model, or every call silently
    # degrades to OpError(rejected) with no failing test.
    payload = {
        "errors": [
            {
                "timestamp": 1000.0,
                "severity": "error",
                "message": "boom",
                "context": "query:screenshot",
            }
        ],
        "total_buffered": 1,
    }
    ops = QueryOperations(HubDisplay(), Hub(), _StubPort(DisplayReplied(payload)))
    result = ops.list_errors(20)
    assert isinstance(result, RecentErrors)
    assert result.errors[0].severity == "error"
    assert result.errors[0].message == "boom"
    assert result.total_buffered == 1


def test_list_errors_maps_a_down_display_to_op_error() -> None:
    ops = QueryOperations(
        HubDisplay(), Hub(), _StubPort(DisplayFault(code="display_unavailable"))
    )
    result = ops.list_errors(20)
    assert isinstance(result, OpError)
    assert result.code == "display_unavailable"
