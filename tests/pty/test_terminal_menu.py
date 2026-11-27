"""Each click starts a new shell; menu failures never drop the owner."""

from __future__ import annotations

import asyncio
import logging
from typing import cast
from unittest.mock import AsyncMock, Mock, patch

import pytest

from punt_lux.client.rest_transport import HubUnavailableError
from punt_lux.kernel.programmer_error import ProgrammerError
from punt_lux.pty.daemon_exchange import DaemonExchange, SessionRefusedError
from punt_lux.pty.entry_runtime import TerminalRuntime
from punt_lux.pty.lifetime import DaemonLifetime
from punt_lux.pty.menu_clients import TerminalClients
from punt_lux.pty.menu_entry import MenuEntryPoint
from punt_lux.pty.menu_listener import TerminalMenu
from punt_lux.pty.menu_process import MenuProcess
from punt_lux.pty.menu_projection import TerminalProjection
from tests.pty.fake_daemon import FakeDaemon


class MenuDoubles:
    @staticmethod
    def clients() -> tuple[TerminalClients, Mock]:
        client = Mock()
        client.callback.register = AsyncMock(return_value=Mock())
        factory = Mock(spec=TerminalClients)
        factory.client.return_value = client
        return cast("TerminalClients", factory), client

    @staticmethod
    def menu(daemon: FakeDaemon) -> tuple[TerminalMenu, Mock]:
        factory, client = MenuDoubles.clients()
        return TerminalMenu(factory, cast("DaemonExchange", daemon)), client

    @staticmethod
    def projection(daemon: FakeDaemon) -> tuple[TerminalProjection, Mock]:
        factory, client = MenuDoubles.clients()
        return TerminalProjection(factory, cast("DaemonExchange", daemon)), client


def test_registration_names_the_entry_and_starts_no_shell() -> None:
    daemon = FakeDaemon()
    projection, client = MenuDoubles.projection(daemon)
    asyncio.run(projection.connected())
    client.callback.register.assert_awaited_once_with("terminal", "New terminal")
    assert daemon.started == []


def test_registration_carries_no_frame_id_so_every_click_runs() -> None:
    projection, client = MenuDoubles.projection(FakeDaemon())
    asyncio.run(projection.connected())
    args, kwargs = client.callback.register.await_args
    assert "frame_id" not in kwargs
    assert len(args) == 2


def test_an_unknown_callback_starts_nothing() -> None:
    daemon = FakeDaemon()
    projection, _client = MenuDoubles.projection(daemon)
    asyncio.run(projection.clicked("unknown"))
    assert daemon.started == []


def test_each_click_starts_a_new_session() -> None:
    daemon = FakeDaemon("t0.1", "t0.2", "t0.3")
    projection, _client = MenuDoubles.projection(daemon)

    async def clicks() -> None:
        for _ in range(3):
            await projection.clicked("terminal")

    asyncio.run(clicks())
    assert daemon.started == ["t0.1", "t0.2", "t0.3"]


def test_a_click_names_no_launcher_and_carries_no_command() -> None:
    daemon = FakeDaemon("t0.1")
    projection, _client = MenuDoubles.projection(daemon)
    asyncio.run(projection.clicked("terminal"))
    (request,) = daemon.requests
    assert (request.launcher, request.label) == ("", "")


def test_a_refused_start_is_logged_and_the_menu_survives() -> None:
    daemon = FakeDaemon()
    daemon.refuse("terminal session limit reached")
    menu, _client = MenuDoubles.menu(daemon)
    asyncio.run(menu._clicked("terminal"))
    assert daemon.started == []


def test_a_click_refused_at_the_limit_warns_without_a_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    daemon = FakeDaemon()
    daemon.refuse("terminal session limit reached")
    menu, _client = MenuDoubles.menu(daemon)
    asyncio.run(menu._clicked("terminal"))
    (record,) = caplog.records
    assert (record.levelno, record.exc_info) == (logging.WARNING, None)
    assert "terminal session limit reached" in record.getMessage()


def test_an_unexpected_listener_error_is_logged_and_the_menu_keeps_serving(
    caplog: pytest.LogCaptureFixture,
) -> None:
    menu, _client = MenuDoubles.menu(FakeDaemon())
    listener = Mock()
    listener.listen = AsyncMock(side_effect=ValueError("unknown frame"))

    async def scenario() -> bool:
        with patch.object(menu._clients, "listener", return_value=listener):
            task = asyncio.create_task(menu.serve())
            await asyncio.sleep(0.3)
            alive = not task.done()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        return alive

    assert asyncio.run(scenario())
    assert any(
        r.levelno >= logging.ERROR and "unknown frame" in str(r.exc_info)
        for r in caplog.records
    )


def test_a_keeper_that_ends_takes_the_menu_down_with_its_error() -> None:
    menu, _client = MenuDoubles.menu(FakeDaemon())

    async def forever() -> None:
        await asyncio.Event().wait()

    listener = Mock()
    listener.listen = AsyncMock(side_effect=forever)
    with (
        patch.object(menu._clients, "listener", return_value=listener),
        patch.object(
            menu._keeper,
            "serve",
            new=AsyncMock(side_effect=ProgrammerError("keeper bug")),
        ),
        pytest.raises(ProgrammerError, match="keeper bug"),
    ):
        asyncio.run(asyncio.wait_for(menu.serve(), timeout=5))


def test_an_owner_watch_that_fails_stops_the_helper_with_its_error() -> None:
    async def never() -> None:
        await asyncio.Event().wait()

    menu = Mock()
    menu.serve = AsyncMock(side_effect=never)
    with (
        patch.object(TerminalMenu, "local", return_value=menu),
        patch.object(
            TerminalRuntime,
            "wait_for_owner",
            new=AsyncMock(side_effect=OSError("owner watch broke")),
        ),
        pytest.raises(OSError, match="owner watch broke"),
    ):
        asyncio.run(asyncio.wait_for(MenuEntryPoint.serve(1), timeout=5))


def test_a_menu_that_ends_stops_the_helper_loudly() -> None:
    async def never(_parent: int) -> None:
        await asyncio.Event().wait()

    menu = Mock()
    menu.serve = AsyncMock(side_effect=ProgrammerError("menu bug"))
    with (
        patch.object(TerminalMenu, "local", return_value=menu),
        patch.object(TerminalRuntime, "wait_for_owner", side_effect=never),
        pytest.raises(ProgrammerError, match="menu bug"),
    ):
        asyncio.run(asyncio.wait_for(MenuEntryPoint.serve(1), timeout=5))


def test_a_reply_without_a_session_is_a_refusal() -> None:
    daemon = FakeDaemon()
    daemon.answer_new_with({})
    projection, _client = MenuDoubles.projection(daemon)
    with pytest.raises(SessionRefusedError, match="without a session"):
        asyncio.run(projection.clicked("terminal"))


def test_a_malformed_reply_does_not_stop_the_menu() -> None:
    daemon = FakeDaemon()
    daemon.answer_new_with({"session": 7})
    menu, _client = MenuDoubles.menu(daemon)
    asyncio.run(menu._clicked("terminal"))


def test_an_unreachable_daemon_does_not_stop_the_menu() -> None:
    daemon = FakeDaemon()
    daemon.go_away(OSError("daemon gone"))
    menu, _client = MenuDoubles.menu(daemon)
    asyncio.run(menu._clicked("terminal"))


@pytest.mark.parametrize(
    "error", [OSError("Hub absent"), HubUnavailableError("Hub absent")]
)
def test_listener_guard_does_not_drop_owner_on_registration_error(
    error: OSError,
) -> None:
    menu, client = MenuDoubles.menu(FakeDaemon())
    client.callback.register.side_effect = error
    asyncio.run(menu._connected())


def test_a_hub_connect_asks_the_keeper_to_reconcile() -> None:
    menu, _client = MenuDoubles.menu(FakeDaemon())
    with patch.object(menu._keeper, "resync") as resync:
        asyncio.run(menu._connected())
    resync.assert_called_once_with()


@pytest.mark.parametrize("operation", ["connect", "click", "listen"])
def test_listener_does_not_swallow_programmer_errors(operation: str) -> None:
    daemon = FakeDaemon()
    error = ProgrammerError("broken invariant")
    daemon.go_away(error)
    menu, client = MenuDoubles.menu(daemon)
    client.callback.register.side_effect = error
    with pytest.raises(ProgrammerError, match="broken invariant"):
        if operation == "connect":
            asyncio.run(menu._connected())
        elif operation == "click":
            asyncio.run(menu._clicked("terminal"))
        else:
            listener = Mock()
            listener.listen = AsyncMock(side_effect=error)
            with patch.object(menu._clients, "listener", return_value=listener):
                asyncio.run(menu.serve())


def test_menu_lifetime_does_not_idle_out_when_empty() -> None:
    lifetime = DaemonLifetime(None)
    assert not lifetime.expired(0, 0)
    assert not lifetime.expired(0, 0)


def test_unstarted_menu_process_close_is_safe() -> None:
    process = MenuProcess()
    process.close()
    process.close()
