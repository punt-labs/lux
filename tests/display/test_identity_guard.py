"""IdentityGuard — the shared fail-closed content-message identity predicate.

Pure unit tests against a real ``SocketListener`` with faked sockets -- no
ImGui, no real subprocess. ``HubReconciliation`` and ``ContentMessageGate``
each hold this guard and are tested against their own wiring in
``test_hub_reconciliation.py`` / ``test_content_message_gate.py``; these
tests exercise the predicate itself directly.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from punt_lux.display.identity_guard import IdentityGuard
from punt_lux.display.socket_server import SocketListener


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


class TestRejectIfUnidentified:
    """The light guard menu/callback-menu/theme messages use uniformly."""

    def test_an_unidentified_fd_is_rejected(self) -> None:
        listener = _make_listener()
        errors: list[str] = []
        guard = IdentityGuard(listener, lambda _sev, msg, _ctx: errors.append(msg))
        sock = _mock_sock(10)

        assert guard.reject_if_unidentified(sock, "MenuMessage") is True
        assert any("MenuMessage" in m for m in errors)

    def test_a_test_kind_fd_is_not_rejected(self) -> None:
        listener = _make_listener()
        listener.register_client_identity(
            10, kind="test", name="probe", connect_time=0.0
        )
        guard = IdentityGuard(listener, lambda _sev, _msg, _ctx: None)

        assert guard.reject_if_unidentified(_mock_sock(10), "MenuMessage") is False

    def test_a_hub_kind_fd_is_not_rejected(self) -> None:
        listener = _make_listener()
        listener.register_client_identity(
            10, kind="hub", name="lux-mcp", connect_time=0.0
        )
        guard = IdentityGuard(listener, lambda _sev, _msg, _ctx: None)

        assert guard.reject_if_unidentified(_mock_sock(10), "ThemeMessage") is False

    def test_a_dead_socket_fails_closed_and_is_observable(self) -> None:
        """``fileno()`` returning ``-1`` (torn down) rejects and records too.

        djb: ``socket.fileno()`` on a torn-down socket returns ``-1`` rather
        than raising -- ``kind_of(-1)`` is ``None`` the same as any other
        never-identified fd, so this is the ordinary reject path, not a
        separate case, and it must not drop the message silently.
        """
        listener = _make_listener()
        errors: list[str] = []
        guard = IdentityGuard(listener, lambda _sev, msg, _ctx: errors.append(msg))

        rejected = guard.reject_if_unidentified(_mock_sock(-1), "CallbackMenuMessage")

        assert rejected is True
        assert any("unidentified" in m and "CallbackMenuMessage" in m for m in errors)

    def test_the_fd_stays_open(self) -> None:
        listener = _make_listener()
        guard = IdentityGuard(listener, lambda _sev, _msg, _ctx: None)
        sock = _mock_sock(10)

        guard.reject_if_unidentified(sock, "MenuMessage")

        sock.close.assert_not_called()


class TestRejectSceneUnlessHub:
    """Scene's own stricter policy: reject and close unless ``kind="hub"``."""

    def test_an_unidentified_fd_is_rejected_and_closed(self) -> None:
        listener = _make_listener()
        guard = IdentityGuard(listener, lambda _sev, _msg, _ctx: None)
        sock = _mock_sock(10)
        listener.clients.append(sock)
        listener.fd_to_client[10] = sock

        rejected = guard.reject_scene_unless_hub(sock)

        assert rejected is True
        sock.close.assert_called_once()

    def test_a_test_kind_fd_is_rejected_and_closed(self) -> None:
        listener = _make_listener()
        listener.register_client_identity(
            10, kind="test", name="probe", connect_time=0.0
        )
        guard = IdentityGuard(listener, lambda _sev, _msg, _ctx: None)
        sock = _mock_sock(10)
        listener.clients.append(sock)
        listener.fd_to_client[10] = sock

        rejected = guard.reject_scene_unless_hub(sock)

        assert rejected is True
        sock.close.assert_called_once()

    def test_a_hub_kind_fd_is_not_rejected(self) -> None:
        listener = _make_listener()
        listener.register_client_identity(
            10, kind="hub", name="lux-mcp", connect_time=0.0
        )
        guard = IdentityGuard(listener, lambda _sev, _msg, _ctx: None)
        sock = _mock_sock(10)

        rejected = guard.reject_scene_unless_hub(sock)

        assert rejected is False
        sock.close.assert_not_called()

    def test_a_dead_socket_fails_closed_and_is_observable(self) -> None:
        """The same ``fileno() == -1`` case, for scene's closing policy."""
        listener = _make_listener()
        errors: list[str] = []
        guard = IdentityGuard(listener, lambda _sev, msg, _ctx: errors.append(msg))
        sock = _mock_sock(-1)
        listener.clients.append(sock)

        rejected = guard.reject_scene_unless_hub(sock)

        assert rejected is True
        assert any("unidentified" in m and "SceneMessage" in m for m in errors)
