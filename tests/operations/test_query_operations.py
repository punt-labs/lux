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
from typing import Self, cast

from punt_lux.display_client import agent_element_factory
from punt_lux.domain.element import Element as DomainElement
from punt_lux.domain.hub.hub import Hub
from punt_lux.domain.hub.hub_display import HubDisplay
from punt_lux.domain.hub.scene_presentation import ScenePresentation
from punt_lux.domain.ids import ConnectionId, SceneId, Topic
from punt_lux.operations.display_reply import DisplayFault, DisplayReplied, DisplayReply
from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.query_clients import ClientList
from punt_lux.operations.models.query_errors import RecentErrors
from punt_lux.operations.models.query_events import RecentEvents
from punt_lux.operations.models.query_inspection import (
    MirrorNotRequested,
    MirrorPresent,
    MirrorUnavailable,
    SceneInspection,
)
from punt_lux.operations.models.query_scenes import SceneList
from punt_lux.operations.queries import QueryOperations


class _ForbiddenPort:
    """A DisplayPort that fails the test if any proxied call is made.

    Injected into the Hub-authoritative reads to prove they never reach around
    to the display.
    """

    def query(self, method: str, params: Mapping[str, object]) -> DisplayReply:
        msg = f"Hub read reached around to the display: query({method!r})"
        raise AssertionError(msg)

    def ping(self, *, now: float) -> DisplayReply:
        raise AssertionError("Hub read reached around to the display: ping()")


class _StubPort:
    """A DisplayPort returning a preset reply for the proxied reads."""

    _reply: DisplayReply

    def __new__(cls, reply: DisplayReply) -> Self:
        self = super().__new__(cls)
        self._reply = reply
        return self

    def query(self, method: str, params: Mapping[str, object]) -> DisplayReply:
        return self._reply

    def ping(self, *, now: float) -> DisplayReply:
        return self._reply


def _seed_scene(store: HubDisplay, *, scene: str, connection: str) -> None:
    """Install a group root with a text child under one connection."""
    group = agent_element_factory().element_from_dict(
        {
            "kind": "group",
            "id": "g1",
            "children": [{"kind": "text", "id": "t1", "content": "hi"}],
        }
    )
    store.show_scene(
        ConnectionId(connection),
        SceneId(scene),
        [cast("DomainElement", group)],
        ScenePresentation(frame_id="frame-a", frame_title="Frame A", layout="single"),
    )


def test_inspect_scene_reads_the_hub_without_touching_the_display() -> None:
    store = HubDisplay()
    _seed_scene(store, scene="s1", connection="c1")
    ops = QueryOperations(store, Hub(), _ForbiddenPort())

    result = ops.inspect_scene("s1")

    assert isinstance(result, SceneInspection)
    assert result.scene_id == "s1"
    root = result.elements[0]
    assert root.id == "g1"
    assert root.render_path in ("abc", "legacy")
    assert root.children[0].id == "t1"
    # The mirror check was not requested, so it is not proxied — a distinct state
    # from "requested but unavailable".
    assert isinstance(result.mirror, MirrorNotRequested)


def test_inspect_scene_mirror_present_when_every_element_is_mirrored() -> None:
    # want_mirror=True proxies the display's per-element reply; the scene-level
    # answer is present only when every element carries the mirror flag.
    store = HubDisplay()
    _seed_scene(store, scene="s1", connection="c1")
    reply = DisplayReplied(
        {
            "scene_id": "s1",
            "element_paths": [
                {"id": "g1", "domain_mirror_present": True},
                {"id": "t1", "domain_mirror_present": True},
            ],
        }
    )
    ops = QueryOperations(store, Hub(), _StubPort(reply))

    result = ops.inspect_scene("s1", want_mirror=True)

    assert isinstance(result, SceneInspection)
    assert result.mirror == MirrorPresent(present=True)


def test_inspect_scene_mirror_not_present_when_one_element_is_missing() -> None:
    store = HubDisplay()
    _seed_scene(store, scene="s1", connection="c1")
    reply = DisplayReplied(
        {
            "element_paths": [
                {"id": "g1", "domain_mirror_present": True},
                {"id": "t1", "domain_mirror_present": False},
            ]
        }
    )
    ops = QueryOperations(store, Hub(), _StubPort(reply))

    result = ops.inspect_scene("s1", want_mirror=True)

    assert isinstance(result, SceneInspection)
    assert result.mirror == MirrorPresent(present=False)


def test_inspect_scene_mirror_unavailable_when_the_display_is_down() -> None:
    # A requested check the display cannot answer is unavailable-with-reason,
    # never silently conflated with "not requested".
    store = HubDisplay()
    _seed_scene(store, scene="s1", connection="c1")
    ops = QueryOperations(
        store, Hub(), _StubPort(DisplayFault(code="display_unavailable"))
    )

    result = ops.inspect_scene("s1", want_mirror=True)

    assert isinstance(result, SceneInspection)
    assert isinstance(result.mirror, MirrorUnavailable)
    assert result.mirror.reason


def test_inspect_scene_unknown_scene_is_not_found() -> None:
    ops = QueryOperations(HubDisplay(), Hub(), _ForbiddenPort())
    result = ops.inspect_scene("ghost")
    assert isinstance(result, OpError)
    assert result.code == "not_found"


def test_list_scenes_reads_the_hub_without_touching_the_display() -> None:
    store = HubDisplay()
    _seed_scene(store, scene="s1", connection="c1")
    ops = QueryOperations(store, Hub(), _ForbiddenPort())

    result = ops.list_scenes()

    assert isinstance(result, SceneList)
    summary = next(s for s in result.scenes if s.scene_id == "s1")
    assert summary.element_count == 2  # the group and its text child
    assert summary.frame_id == "frame-a"
    assert summary.owner == "c1"
    frame = next(f for f in result.frames if f.frame_id == "frame-a")
    assert frame.scene_ids == ["s1"]
    assert frame.layout == "tab"  # no explicit frame layout defaults to tab


def test_list_clients_reads_the_hub_session_registry() -> None:
    store = HubDisplay()
    _seed_scene(store, scene="s1", connection="c1")
    hub = Hub()
    hub.register_writer(ConnectionId("c1"), lambda _msg: None)
    hub.subscribe(ConnectionId("c1"), Topic("work.saved"))
    ops = QueryOperations(store, hub, _ForbiddenPort())

    result = ops.list_clients(now=0.0)

    assert isinstance(result, ClientList)
    client = next(c for c in result.clients if c.connection_id == "c1")
    assert client.subscribed_topics == ["work.saved"]
    assert client.owned_scenes == ["s1"]
    assert client.connected_seconds <= 0.0


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
