"""Launcher callbacks register fresh and publish metadata, never unsolicited PTYs."""

from __future__ import annotations

import asyncio
from typing import cast
from unittest.mock import AsyncMock, Mock, patch

import pytest

from punt_lux.client.rest_transport import HubUnavailableError
from punt_lux.kernel.programmer_error import ProgrammerError
from punt_lux.pty.lifetime import DaemonLifetime
from punt_lux.pty.menu_clients import TerminalClients
from punt_lux.pty.menu_listener import TerminalMenu
from punt_lux.pty.menu_process import MenuProcess
from punt_lux.pty.menu_projection import TerminalProjection
from punt_lux.wire.operations import OpError, SceneShown


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
    client.callback.register.assert_awaited_once_with(
        "terminal", "Terminal", frame_id="terminal"
    )
    client.scene.show.assert_not_awaited()


def test_registration_carries_the_frame_id_so_a_closed_frame_reopens() -> None:
    """The Clients-menu entry must register with the frame id, or a repeat click

    after the user closes the terminal no-ops against the still-installed scene
    and the terminal launches only once.
    """
    factory, client = MenuDoubles.clients()
    projection = TerminalProjection(factory)
    asyncio.run(projection.connected())
    _args, kwargs = client.callback.register.await_args
    assert kwargs.get("frame_id") == "terminal"


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


@pytest.mark.parametrize(
    "error", [OSError("Hub absent"), HubUnavailableError("Hub absent")]
)
def test_listener_guard_does_not_drop_owner_on_projection_error(error: OSError) -> None:
    factory, client = MenuDoubles.clients()
    client.callback.register.side_effect = error
    client.scene.show.side_effect = error
    with patch("punt_lux.pty.menu_listener.TerminalClients", return_value=factory):
        menu = TerminalMenu()
    asyncio.run(menu._connected())
    asyncio.run(menu._clicked("terminal"))


@pytest.mark.parametrize("operation", ["connect", "click", "listen"])
def test_listener_does_not_swallow_programmer_errors(operation: str) -> None:
    factory, client = MenuDoubles.clients()
    with patch("punt_lux.pty.menu_listener.TerminalClients", return_value=factory):
        menu = TerminalMenu()
    error = ProgrammerError("broken invariant")
    client.callback.register.side_effect = error
    client.scene.show.side_effect = error
    with pytest.raises(ProgrammerError, match="broken invariant"):
        if operation == "connect":
            asyncio.run(menu._connected())
        elif operation == "click":
            asyncio.run(menu._clicked("terminal"))
        else:
            listener = Mock()
            listener.listen = AsyncMock(side_effect=error)
            with patch.object(factory, "listener", return_value=listener):
                asyncio.run(menu.serve())


def test_menu_lifetime_does_not_idle_out_when_empty() -> None:
    lifetime = DaemonLifetime(None)
    assert not lifetime.expired(0, 0)
    assert not lifetime.expired(0, 0)


def test_unstarted_menu_process_close_is_safe() -> None:
    process = MenuProcess()
    process.close()
    process.close()
