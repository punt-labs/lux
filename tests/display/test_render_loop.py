"""RenderLoop — DES-068 wiring, and what a close tells the outside world.

``HubReconciliation`` (``tests/display/test_hub_reconciliation.py``) owns the
preemption and purge policy itself; these tests verify ``RenderLoop`` wires its
socket-callback dispatch to that policy correctly.

They also pin down the silence DES-065 R8 establishes. Where a window sits is
the Display's own business, so *no* close tells anyone anything — not the purge
that used to be exempted by a ``notify=False`` flag, and not the user's click on
the ✕, which used to send a ``frame_close`` the Hub answered by deleting the
frame's scenes. With both paths silent the flag has nothing left to distinguish,
so it is gone too.
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
        hub_identify = ConnectMessage(name="lux-mcp", kind="hub")
        server._handle_message(identify_sock, hub_identify)
        server._handle_message(identify_sock, HubManifestMessage(scene_ids=()))

        assert server._scenes.resolve_scene("s1") is None


class TestAClosePassesNoWord:
    """No close reaches a client: not the Hub's purge, and not the user's ✕."""

    def test_a_manifest_driven_purge_sends_no_frame_close_event(self) -> None:
        server = _make_server()
        owner_sock = _mock_sock(10)
        server._socket_listener.clients.append(owner_sock)
        server._socket_listener.fd_to_client[10] = owner_sock
        server._handle_scene(owner_sock, _make_scene("s1", "f1"))
        owner_sock.send.reset_mock()  # drop the scene-install ack, not under test

        identify_sock = _mock_sock(20)
        hub_identify = ConnectMessage(name="lux-mcp", kind="hub")
        server._handle_message(identify_sock, hub_identify)
        server._handle_message(identify_sock, HubManifestMessage(scene_ids=()))

        # The purge silently drops the frame -- no frame_close reaches the
        # (already-superseded) owner's socket.
        owner_sock.send.assert_not_called()
        assert "f1" not in server._scenes.frames

    def test_a_user_initiated_close_tells_the_owner_nothing(self) -> None:
        """X8 — closing is Display-owned, so the client hears about it not at all.

        This is the send F4 retires. The Hub answered a ``frame_close`` by
        removing the frame's scenes and marking them dirty; the replicator then
        pushed them back empty, and an empty push is the dispose path. So even a
        Display that kept its closed frame perfectly would have had it thrown out
        one round trip later, by the Hub, on the user's own close.
        """
        server = _make_server()
        owner_sock = _mock_sock(10)
        server._socket_listener.clients.append(owner_sock)
        server._socket_listener.fd_to_client[10] = owner_sock
        server._handle_scene(owner_sock, _make_scene("s1", "f1"))
        owner_sock.send.reset_mock()  # drop the scene-install ack, not under test

        server._close_frame("f1")

        owner_sock.send.assert_not_called()

    def test_a_user_initiated_close_keeps_the_frame_and_its_scene(self) -> None:
        """The user shut a window; the content behind it is untouched."""
        server = _make_server()
        owner_sock = _mock_sock(10)
        server._handle_scene(owner_sock, _make_scene("s1", "f1"))

        server._close_frame("f1")

        assert server._scenes.frames["f1"].is_closed is True
        assert server._scenes.resolve_scene("s1") is not None

    def test_a_close_drops_the_frames_queued_interactions(self) -> None:
        """X6 — a button in a window the user just shut must not fire afterwards.

        The drain is Display-local: it reaches nothing outside this process,
        which is what makes it a visibility-side action rather than a content one.
        """
        server = _make_server()
        owner_sock = _mock_sock(10)
        server._handle_scene(owner_sock, _make_scene("s1", "f1"))
        server._event_queue.append(
            RemoteEventHandlerInvocation(
                element_id="s1-t", action="click", scene_id="s1"
            )
        )

        server._close_frame("f1")

        assert server._event_queue == []

    def test_a_close_leaves_another_frames_queued_interactions_alone(self) -> None:
        """The drain is for the frame that was shut, not for the workspace."""
        server = _make_server()
        owner_sock = _mock_sock(10)
        server._handle_scene(owner_sock, _make_scene("s1", "f1"))
        server._handle_scene(owner_sock, _make_scene("s2", "f2"))
        server._event_queue.append(
            RemoteEventHandlerInvocation(
                element_id="s2-t", action="click", scene_id="s2"
            )
        )

        server._close_frame("f1")

        assert [e.element_id for e in server._event_queue] == ["s2-t"]


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
