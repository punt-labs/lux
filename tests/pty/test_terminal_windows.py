"""Windows are shown one per session, removed alone, and failures name the session."""

from __future__ import annotations

import asyncio

import pytest

from punt_lux.pty.listed_session import ListedSession
from punt_lux.pty.sync_plan import SyncPlan
from punt_lux.pty.terminal_windows import TerminalWindows, WindowRefusedError
from tests.pty.stub_hub import StubHub


def _session(name: str) -> ListedSession:
    return ListedSession(name, f"label-{name}", "running")


def test_each_session_opens_its_own_scene_and_titled_frame() -> None:
    hub = StubHub()
    windows = TerminalWindows(hub.clients)

    async def scenario() -> None:
        for name in ("t0.1", "t0.2", "t0.3"):
            await windows.open(_session(name))

    asyncio.run(scenario())
    assert sorted(hub.scenes) == ["terminal-t0.1", "terminal-t0.2", "terminal-t0.3"]
    assert hub.scenes["terminal-t0.2"].title == "label-t0.2"


def test_closing_one_window_leaves_the_others() -> None:
    hub = StubHub()
    windows = TerminalWindows(hub.clients)

    async def scenario() -> None:
        await windows.open(_session("t0.1"))
        await windows.open(_session("t0.2"))
        await windows.close("t0.1")

    asyncio.run(scenario())
    assert sorted(hub.scenes) == ["terminal-t0.2"]


def test_refresh_reads_the_windows_the_hub_holds_not_memory() -> None:
    hub = StubHub()
    windows = TerminalWindows(hub.clients)

    async def scenario() -> None:
        await windows.open(_session("t0.1"))
        hub.come_up(lose_scenes=True)
        await windows.refresh()

    asyncio.run(scenario())
    assert windows.shown == frozenset()


def test_an_unreachable_hub_is_a_window_failure_naming_the_session() -> None:
    hub = StubHub()
    hub.go_down()
    windows = TerminalWindows(hub.clients)
    with pytest.raises(WindowRefusedError, match=r"t0\.4"):
        asyncio.run(windows.open(_session("t0.4")))


def test_a_refused_scene_is_a_window_failure_naming_the_session() -> None:
    hub = StubHub()
    hub.refuse("no room")
    windows = TerminalWindows(hub.clients)
    with pytest.raises(WindowRefusedError, match=r"t0\.4.*no room"):
        asyncio.run(windows.open(_session("t0.4")))
    assert windows.shown == frozenset()


def test_one_refused_window_does_not_stop_the_others_opening() -> None:
    hub = StubHub()
    hub.refuse_scene("terminal-t0.1", "no room")
    windows = TerminalWindows(hub.clients)
    plan = SyncPlan((_session("t0.1"), _session("t0.2"), _session("t0.3")), ())
    with pytest.raises(WindowRefusedError, match=r"t0\.1.*no room"):
        asyncio.run(windows.apply(plan))
    assert windows.shown == frozenset({"t0.2", "t0.3"})


def test_a_quarantined_window_is_not_counted_as_shown() -> None:
    hub = StubHub()
    windows = TerminalWindows(hub.clients)

    async def scenario() -> None:
        await windows.open(_session("t0.1"))
        await windows.open(_session("t0.2"))
        hub.quarantine("terminal-t0.1")
        await windows.refresh()

    asyncio.run(scenario())
    assert windows.shown == frozenset({"t0.2"})


def test_other_scenes_are_not_taken_for_terminal_windows() -> None:
    hub = StubHub()
    windows = TerminalWindows(hub.clients)

    async def scenario() -> None:
        from punt_lux.wire.operations import RenderRequest

        await hub.show(RenderRequest(scene_id="beads", elements=[]))
        await windows.refresh()

    asyncio.run(scenario())
    assert windows.shown == frozenset()


def test_a_foreign_terminal_scene_is_not_adopted() -> None:
    hub = StubHub()
    hub.add_foreign("terminal-x")
    windows = TerminalWindows(hub.clients)
    asyncio.run(windows.refresh())
    assert windows.shown == frozenset()


def test_a_foreign_terminal_scene_is_not_cleared() -> None:
    hub = StubHub()
    hub.add_foreign("terminal-x")
    windows = TerminalWindows(hub.clients)

    async def scenario() -> None:
        await windows.refresh()
        await windows.close("x")

    asyncio.run(scenario())
    assert hub.foreign == frozenset({"terminal-x"})


def test_a_foreign_scene_does_not_stop_the_same_session_opening() -> None:
    hub = StubHub()
    hub.add_foreign("terminal-t0.1")
    windows = TerminalWindows(hub.clients)

    async def scenario() -> None:
        await windows.refresh()
        await windows.open(_session("t0.1"))

    asyncio.run(scenario())
    assert sorted(hub.scenes) == ["terminal-t0.1"]
