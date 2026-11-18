"""Launcher callbacks register fresh and publish metadata, never unsolicited PTYs."""

from __future__ import annotations

import asyncio
from typing import cast
from unittest.mock import AsyncMock, Mock

from punt_lux.operations import OpError, SceneShown
from punt_lux.ptyd.lifetime import DaemonLifetime
from punt_lux.ptyd.menu_clients import TerminalClients
from punt_lux.ptyd.menu_listener import TerminalMenu
from punt_lux.ptyd.menu_process import MenuProcess
from punt_lux.ptyd.menu_projection import TerminalProjection


class MenuDoubles:
    @staticmethod
    def clients() -> tuple[TerminalClients, Mock]:
        client = Mock()
        client.callback.register = AsyncMock(return_value=Mock())
        client.scene.show = AsyncMock(return_value=SceneShown(scene_id="terminal"))
        factory = Mock(spec=TerminalClients)
        factory.client.return_value = client
        return cast("TerminalClients", factory), client


def test_registration_without_click_does_not_publish_a_shell_scene() -> None:
    factory, client = MenuDoubles.clients()
    projection = TerminalProjection(factory)
    asyncio.run(projection.connected())
    client.callback.register.assert_awaited_once_with("terminal", "Terminal")
    client.scene.show.assert_not_awaited()


def test_click_and_reconnect_reuse_one_terminal_session() -> None:
    factory, client = MenuDoubles.clients()
    projection = TerminalProjection(factory)
    asyncio.run(projection.clicked("unknown"))
    client.scene.show.assert_not_awaited()
    asyncio.run(projection.clicked("terminal"))
    asyncio.run(projection.connected())
    requests = [call.args[0] for call in client.scene.show.await_args_list]
    assert len(requests) == 2
    assert requests[0].scene_id == requests[1].scene_id == "terminal"
    assert requests[0].elements == requests[1].elements
    assert requests[0].elements[0]["session"] == "luxd-pty-terminal"
    assert "command" not in requests[0].elements[0]


def test_rejected_click_is_not_republished_on_reconnect() -> None:
    factory, client = MenuDoubles.clients()
    client.scene.show.return_value = OpError(code="rejected", reason="no")
    projection = TerminalProjection(factory)
    asyncio.run(projection.clicked("terminal"))
    asyncio.run(projection.connected())
    assert client.scene.show.await_count == 1


def test_listener_guard_does_not_drop_owner_on_projection_error() -> None:
    factory, client = MenuDoubles.clients()
    client.callback.register.side_effect = OSError("Hub absent")
    client.scene.show.side_effect = OSError("Hub absent")
    menu = TerminalMenu(factory)
    asyncio.run(menu._connected())
    asyncio.run(menu._clicked("terminal"))


def test_menu_lifetime_does_not_idle_out_when_empty() -> None:
    lifetime = DaemonLifetime(None)
    assert not lifetime.expired(0, 0)
    assert not lifetime.expired(0, 0)


def test_unstarted_menu_process_close_is_safe() -> None:
    process = MenuProcess()
    process.close()
    process.close()
