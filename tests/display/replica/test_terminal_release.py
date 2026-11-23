"""Every way a terminal element leaves the replica releases its session."""

from __future__ import annotations

from pathlib import Path
from typing import Self

import pytest

from punt_lux.display.replica import SceneReplica
from punt_lux.display.terminal.remote_phase import RemotePhase
from punt_lux.display.terminal.remote_pool import RemotePool
from punt_lux.wire.model import Element, GroupElement, SceneMessage, TextElement
from punt_lux.wire.model.elements.terminal import TerminalElement
from punt_lux.wire.model.identity import HubId

_HUB = HubId.stub()


class Held:
    """Records the latest set of terminal sessions the replica still names."""

    _names: frozenset[str]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._names = frozenset({"<never reported>"})
        return self

    def __call__(self, names: frozenset[str]) -> None:
        self._names = names

    @property
    def names(self) -> frozenset[str]:
        return self._names


def _scene(scene_id: str, *sessions: str) -> SceneMessage:
    terminals: list[Element] = [
        TerminalElement(id=f"{s}-el", session=s) for s in sessions
    ]
    return SceneMessage(
        id=scene_id,
        elements=terminals or [TextElement(id=f"{scene_id}-t", content="x")],
        frame_id=scene_id,
    )


@pytest.fixture
def held() -> Held:
    return Held()


@pytest.fixture
def replica(held: Held) -> SceneReplica:
    return SceneReplica(on_scene_replaced=lambda _ids: None, on_terminals_held=held)


def test_empty_push_releases(replica: SceneReplica, held: Held) -> None:
    replica.handle_framed_scene(_scene("s1", "t1"), 1)
    assert held.names == frozenset({"t1"})
    replica.handle_framed_scene(SceneMessage(id="s1", elements=[], frame_id="s1"), 1)
    assert held.names == frozenset()


def test_clear_all_releases(replica: SceneReplica, held: Held) -> None:
    replica.handle_framed_scene(_scene("s1", "t1"), 1)
    replica.clear_all()
    assert held.names == frozenset()


def test_dispose_frame_releases(replica: SceneReplica, held: Held) -> None:
    replica.handle_framed_scene(_scene("s1", "t1"), 1)
    replica.handle_framed_scene(_scene("s2", "t2"), 1)
    replica.dispose_frame("s1", _HUB)
    assert held.names == frozenset({"t2"})


def test_replace_scene_without_the_element_releases(
    replica: SceneReplica, held: Held
) -> None:
    replica.handle_framed_scene(_scene("s1", "t1", "t2"), 1)
    replica.handle_framed_scene(_scene("s1", "t2"), 1)
    assert held.names == frozenset({"t2"})


def test_nested_terminal_is_found(replica: SceneReplica, held: Held) -> None:
    group = GroupElement(id="g", children=[TerminalElement(id="e", session="t9")])
    replica.handle_framed_scene(SceneMessage(id="s", elements=[group], frame_id="s"), 1)
    assert held.names == frozenset({"t9"})


def test_hidden_frame_keeps_its_session(replica: SceneReplica, held: Held) -> None:
    replica.handle_framed_scene(_scene("s1", "t1"), 1)
    replica.close("s1")
    replica.handle_framed_scene(_scene("s2", "t2"), 1)
    assert held.names == frozenset({"t1", "t2"})


def test_cache_leak_trace_name_reuse_gets_fresh_replica() -> None:
    """Model trace: shell exits, scene cleared, same name returns for a new shell."""
    pool = RemotePool(Path("/nonexistent/luxd-pty.sock"))
    replica = SceneReplica(
        on_scene_replaced=lambda _ids: None, on_terminals_held=pool.retain_only
    )
    replica.handle_framed_scene(_scene("terminal-n", "n"), 1)  # ReplicaAttach
    dead = pool.get("n", "")
    dead.fail("process exited")  # ReplicaEnds
    replica.handle_framed_scene(
        SceneMessage(id="terminal-n", elements=[], frame_id="terminal-n"), 1
    )  # HelperSync: scene cleared
    replica.handle_framed_scene(_scene("terminal-n", "n"), 1)  # scene returns
    live = pool.get("n", "")
    assert live is not dead
    assert live.phase is RemotePhase.CONNECTING


def test_moving_a_scene_to_another_frame_keeps_its_session() -> None:
    reports: list[frozenset[str]] = []

    def record(names: frozenset[str]) -> None:
        reports.append(names)

    moving = SceneReplica(on_scene_replaced=lambda _ids: None, on_terminals_held=record)
    moving.handle_framed_scene(_scene("s1", "t1"), 1)
    reports.clear()
    moved = SceneMessage(
        id="s1",
        elements=[TerminalElement(id="t1-el", session="t1")],
        frame_id="elsewhere",
    )
    moving.handle_framed_scene(moved, 1)
    assert all("t1" in names for names in reports)
    assert reports
