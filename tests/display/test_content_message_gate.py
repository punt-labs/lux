"""ContentMessageGate — menu/callback-menu/theme installs only from an identified fd.

Pure unit tests against a real ``IdentityGuard``/``SocketListener`` with a
faked socket and doubled ``menus``/``apply_theme`` collaborators -- no ImGui,
no real subprocess.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from punt_lux.display.content_message_gate import ContentMessageGate
from punt_lux.display.identity_guard import IdentityGuard
from punt_lux.display.socket_server import SocketListener
from punt_lux.domain.hub_id import HubId
from punt_lux.protocol import CallbackMenuMessage, MenuMessage, ThemeMessage


def _mock_sock(fd: int) -> MagicMock:
    sock = MagicMock()
    sock.fileno.return_value = fd
    return sock


def _make_listener() -> SocketListener:
    return SocketListener(
        on_message=lambda _sock, _msg: None,
        on_client_disconnected=lambda _fd: None,
        on_error=lambda _sev, _msg, _ctx: None,
    )


def _make_gate(
    listener: SocketListener, menus: MagicMock, apply_theme: MagicMock
) -> ContentMessageGate:
    identity = IdentityGuard(listener, lambda _sev, _msg, _ctx: None)
    return ContentMessageGate(menus=menus, apply_theme=apply_theme, identity=identity)


class TestHandleAgentMenus:
    def test_installs_from_a_hub_kind_fd(self) -> None:
        listener = _make_listener()
        listener.register_client_identity(
            10, kind="hub", name="lux-mcp", connect_time=0.0
        )
        menus, apply_theme = MagicMock(), MagicMock()
        gate = _make_gate(listener, menus, apply_theme)
        msg = MenuMessage(menus=[{"label": "File", "items": []}])

        gate.handle_agent_menus(_mock_sock(10), msg)

        menus.replace_agent_menus.assert_called_once_with(msg.menus)

    def test_installs_from_a_test_kind_fd(self) -> None:
        listener = _make_listener()
        listener.register_client_identity(
            10, kind="test", name="probe", connect_time=0.0
        )
        menus, apply_theme = MagicMock(), MagicMock()
        gate = _make_gate(listener, menus, apply_theme)
        msg = MenuMessage(menus=[{"label": "File", "items": []}])

        gate.handle_agent_menus(_mock_sock(10), msg)

        menus.replace_agent_menus.assert_called_once_with(msg.menus)

    def test_rejects_an_unidentified_fd(self) -> None:
        listener = _make_listener()
        menus, apply_theme = MagicMock(), MagicMock()
        gate = _make_gate(listener, menus, apply_theme)

        gate.handle_agent_menus(_mock_sock(10), MenuMessage(menus=[]))

        menus.replace_agent_menus.assert_not_called()


class TestHandleCallbackMenus:
    def test_installs_from_an_identified_fd(self) -> None:
        listener = _make_listener()
        listener.register_client_identity(
            10, kind="hub", name="lux-mcp", connect_time=0.0
        )
        menus, apply_theme = MagicMock(), MagicMock()
        gate = _make_gate(listener, menus, apply_theme)
        msg = CallbackMenuMessage(submenus=[{"label": "Clients", "items": []}])

        gate.handle_callback_menus(_mock_sock(10), msg)

        menus.replace_callback_menus.assert_called_once_with(msg.submenus, HubId.stub())

    def test_rejects_an_unidentified_fd(self) -> None:
        listener = _make_listener()
        menus, apply_theme = MagicMock(), MagicMock()
        gate = _make_gate(listener, menus, apply_theme)

        gate.handle_callback_menus(_mock_sock(10), CallbackMenuMessage(submenus=[]))

        menus.replace_callback_menus.assert_not_called()


class TestHandleTheme:
    def test_applies_from_an_identified_fd(self) -> None:
        listener = _make_listener()
        listener.register_client_identity(
            10, kind="hub", name="lux-mcp", connect_time=0.0
        )
        menus, apply_theme = MagicMock(), MagicMock()
        gate = _make_gate(listener, menus, apply_theme)

        gate.handle_theme(_mock_sock(10), ThemeMessage(theme="imgui_colors_light"))

        apply_theme.assert_called_once_with("imgui_colors_light")

    def test_rejects_an_unidentified_fd(self) -> None:
        listener = _make_listener()
        menus, apply_theme = MagicMock(), MagicMock()
        gate = _make_gate(listener, menus, apply_theme)

        gate.handle_theme(_mock_sock(10), ThemeMessage(theme="imgui_colors_light"))

        apply_theme.assert_not_called()

    def test_a_dead_socket_fails_closed_and_is_observable(self) -> None:
        """``fileno() == -1`` (torn-down socket) flows through the same reject path.

        The gate does no fd extraction of its own -- ``IdentityGuard`` owns
        that -- so this proves the shared guard's fail-closed behavior
        reaches the gate's callers too, not just scene's.
        """
        listener = _make_listener()
        errors: list[str] = []
        menus, apply_theme = MagicMock(), MagicMock()
        identity = IdentityGuard(listener, lambda _sev, msg, _ctx: errors.append(msg))
        gate = ContentMessageGate(
            menus=menus, apply_theme=apply_theme, identity=identity
        )

        gate.handle_theme(_mock_sock(-1), ThemeMessage(theme="imgui_colors_light"))

        apply_theme.assert_not_called()
        assert any("unidentified" in m and "ThemeMessage" in m for m in errors)
