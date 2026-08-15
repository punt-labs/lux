"""RenderLoop — DES-068 wiring: connect/manifest dispatch and the notify guard.

``HubReconciliation`` (``tests/display/test_hub_reconciliation.py``) owns the
preemption and purge policy itself; these tests verify ``RenderLoop`` wires its
socket-callback dispatch to that policy correctly, and — the design's own
regression guard — that a manifest-driven purge never notifies a dead owner
(``notify=False``) while every pre-existing user-initiated close keeps
notifying (``notify=True``, unchanged).
"""

from __future__ import annotations

from unittest.mock import MagicMock

from punt_lux.display import RenderLoop
from punt_lux.protocol import (
    ConnectMessage,
    HubManifestMessage,
    RemoteEventHandlerInvocation,
    SceneMessage,
    TextElement,
)


def _make_server() -> RenderLoop:
    return RenderLoop("/tmp/test-lux-hub-reconciliation.sock")


def _mock_sock(fd: int) -> MagicMock:
    sock = MagicMock()
    sock.send.side_effect = len
    sock.fileno.return_value = fd
    return sock


def _make_scene(scene_id: str, frame_id: str | None = None) -> SceneMessage:
    return SceneMessage(
        id=scene_id,
        elements=[TextElement(id=f"{scene_id}-t", content="x")],
        frame_id=frame_id if frame_id is not None else scene_id,
    )


class TestHandleConnectDispatch:
    def test_a_second_hub_identify_preempts_the_first_via_the_real_socket_listener(
        self,
    ) -> None:
        server = _make_server()
        old_sock, new_sock = _mock_sock(10), _mock_sock(20)
        server._socket_listener.clients.append(old_sock)
        server._socket_listener.fd_to_client[10] = old_sock

        server._handle_message(old_sock, ConnectMessage(name="lux-mcp", kind="hub"))
        assert server._socket_listener.hub_fd_for("lux-mcp") == 10

        server._socket_listener.clients.append(new_sock)
        server._socket_listener.fd_to_client[20] = new_sock
        server._handle_message(new_sock, ConnectMessage(name="lux-mcp", kind="hub"))

        assert old_sock not in server._socket_listener.clients
        assert server._socket_listener.hub_fd_for("lux-mcp") == 20

    def test_a_test_identify_is_recorded_without_preemption(self) -> None:
        server = _make_server()
        sock = _mock_sock(10)

        server._handle_message(sock, ConnectMessage(name="quarry", kind="test"))

        assert server._socket_listener.client_names[10] == "quarry"
        assert server._socket_listener.hub_fd_for("quarry") is None


class TestHandleManifestDispatch:
    def test_a_manifest_purges_a_ghost_scene_through_the_real_dispatch(self) -> None:
        server = _make_server()
        owner_sock = _mock_sock(10)
        server._handle_message(owner_sock, _make_scene("s1"))
        assert server._scenes.resolve_scene("s1") is not None

        identify_sock = _mock_sock(20)
        server._handle_message(identify_sock, HubManifestMessage(scene_ids=()))

        assert server._scenes.resolve_scene("s1") is None


class TestNotifyRegressionGuard:
    """Regression guard: a purge stays silent, a user-initiated close still notifies."""

    def test_a_manifest_driven_purge_sends_no_frame_close_event(self) -> None:
        server = _make_server()
        owner_sock = _mock_sock(10)
        server._socket_listener.clients.append(owner_sock)
        server._socket_listener.fd_to_client[10] = owner_sock
        server._handle_scene(owner_sock, _make_scene("s1", "f1"))
        owner_sock.send.reset_mock()  # drop the scene-install ack, not under test

        identify_sock = _mock_sock(20)
        server._handle_message(identify_sock, HubManifestMessage(scene_ids=()))

        # The purge silently drops the frame -- no frame_close reaches the
        # (already-superseded) owner's socket.
        owner_sock.send.assert_not_called()
        assert "f1" not in server._scenes.frames

    def test_a_user_initiated_close_still_notifies_the_owner(self) -> None:
        """Regression guard: this design must not change the existing close paths."""
        server = _make_server()
        owner_sock = _mock_sock(10)
        server._socket_listener.clients.append(owner_sock)
        server._socket_listener.fd_to_client[10] = owner_sock
        server._handle_scene(owner_sock, _make_scene("s1", "f1"))
        owner_sock.send.reset_mock()  # drop the scene-install ack, not under test

        server._close_frame("f1")  # notify=True default, the World-menu close path

        owner_sock.send.assert_called_once()
        sent = bytes(owner_sock.send.call_args[0][0])
        assert b"frame_close" in sent


class TestConnectMessageStillDispatchesThroughHandleMessage:
    """Baseline regression guard for the dispatch table itself."""

    def test_connect_message_is_routed(self) -> None:
        server = _make_server()
        sock = _mock_sock(10)

        server._handle_message(sock, ConnectMessage(name="quarry", kind="test"))

        assert server._socket_listener.client_names[10] == "quarry"

    def test_an_unrelated_event_is_unaffected_by_the_new_wiring(self) -> None:
        server = _make_server()
        sock = _mock_sock(10)
        server._event_queue.append(
            RemoteEventHandlerInvocation(element_id="b1", action="click", ts=1.0)
        )

        server._handle_message(sock, ConnectMessage(name="quarry", kind="test"))

        assert len(server._event_queue) == 1  # untouched by the identify


class TestSceneRejectionFromTestKind:
    """A ``kind="test"`` connection may observe, not install (DES-068 ruling)."""

    def test_a_scene_from_a_test_kind_fd_is_rejected_and_the_fd_closed(self) -> None:
        server = _make_server()
        sock = _mock_sock(10)
        server._socket_listener.clients.append(sock)
        server._socket_listener.fd_to_client[10] = sock

        server._handle_message(sock, ConnectMessage(name="probe", kind="test"))
        server._handle_message(sock, _make_scene("s1"))

        assert server._scenes.resolve_scene("s1") is None
        sock.close.assert_called_once()
        assert sock not in server._socket_listener.clients

    def test_the_rejection_surfaces_via_list_errors(self) -> None:
        server = _make_server()
        sock = _mock_sock(10)
        server._socket_listener.clients.append(sock)
        server._socket_listener.fd_to_client[10] = sock

        server._handle_message(sock, ConnectMessage(name="probe", kind="test"))
        server._handle_message(sock, _make_scene("s1"))

        errors = server._query_router.handle_query("list_errors", None)
        assert errors.result is not None
        messages = [e["message"] for e in errors.result["errors"]]
        assert any("test-kind connection" in m for m in messages)

    def test_a_scene_from_a_hub_kind_fd_still_installs_normally(self) -> None:
        server = _make_server()
        sock = _mock_sock(10)
        server._socket_listener.clients.append(sock)
        server._socket_listener.fd_to_client[10] = sock

        server._handle_message(sock, ConnectMessage(name="lux-mcp", kind="hub"))
        server._handle_message(sock, _make_scene("s1"))

        assert server._scenes.resolve_scene("s1") is not None
        assert sock in server._socket_listener.clients

    def test_a_scene_from_an_unidentified_fd_still_installs_normally(self) -> None:
        """No ConnectMessage at all is unaffected -- only a declared 'test' rejects."""
        server = _make_server()
        sock = _mock_sock(10)

        server._handle_message(sock, _make_scene("s1"))

        assert server._scenes.resolve_scene("s1") is not None
