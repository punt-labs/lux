"""HubReconciliation — single-owner Hub preemption and manifest purge (DES-068).

Pure unit tests against a real ``SocketListener`` and ``SceneReplica`` with
faked sockets — no ImGui, no real subprocess. The harness/subprocess test
that exercises the real wire protocol end to end lives in
``tests/integration/test_hub_display_reconciliation.py``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from punt_lux.display.hub_reconciliation import HubReconciliation
from punt_lux.display.replica import SceneReplica
from punt_lux.display.socket_server import SocketListener
from punt_lux.protocol import (
    ConnectMessage,
    HubManifestMessage,
    SceneMessage,
    TextElement,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    import pytest


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


def _make_reconciliation(
    listener: SocketListener,
    scenes: SceneReplica,
    close_frame: Callable[[str], None] | None = None,
) -> HubReconciliation:
    return HubReconciliation(
        listener,
        scenes,
        close_frame or (lambda _fid: None),
        lambda _sev, _msg, _ctx: None,
    )


def _make_scene(scene_id: str, frame_id: str | None = None) -> SceneMessage:
    # A non-empty push — an empty one is a removal, not a scene (SceneReplica).
    return SceneMessage(
        id=scene_id,
        elements=[TextElement(id=f"{scene_id}-t", content="x")],
        frame_id=frame_id if frame_id is not None else scene_id,
    )


class TestHandleConnect:
    """Preemption: at most one connection ever holds ``kind="hub", name``."""

    def test_a_kind_hub_identify_is_recorded(self) -> None:
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        reconciliation = _make_reconciliation(listener, scenes)
        sock = _mock_sock(10)

        reconciliation.handle_connect(sock, ConnectMessage(name="lux-mcp", kind="hub"))

        assert listener.hub_fd_for("lux-mcp") == 10

    def test_a_test_identify_never_preempts_or_marks_hub(self) -> None:
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        reconciliation = _make_reconciliation(listener, scenes)
        sock = _mock_sock(10)

        probe = ConnectMessage(name="quarry", kind="test")
        reconciliation.handle_connect(sock, probe)

        assert listener.hub_fd_for("quarry") is None
        assert listener.client_names[10] == "quarry"
        assert listener.kind_of(10) == "test"

    def test_a_second_hub_identify_forcibly_disconnects_the_first(self) -> None:
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        reconciliation = _make_reconciliation(listener, scenes)
        old_sock, new_sock = _mock_sock(10), _mock_sock(20)
        listener.clients.append(old_sock)
        listener.fd_to_client[10] = old_sock

        reconciliation.handle_connect(
            old_sock, ConnectMessage(name="lux-mcp", kind="hub")
        )
        assert listener.hub_fd_for("lux-mcp") == 10

        listener.clients.append(new_sock)
        listener.fd_to_client[20] = new_sock
        reconciliation.handle_connect(
            new_sock, ConnectMessage(name="lux-mcp", kind="hub")
        )

        old_sock.close.assert_called_once()  # forcibly removed
        assert old_sock not in listener.clients
        assert listener.hub_fd_for("lux-mcp") == 20  # the new claimant, and only it

    def test_a_hub_identify_with_no_predecessor_preempts_nothing(self) -> None:
        """The ordinary restart case: the old process's socket is already gone."""
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        reconciliation = _make_reconciliation(listener, scenes)
        sock = _mock_sock(10)

        reconciliation.handle_connect(sock, ConnectMessage(name="lux-mcp", kind="hub"))

        sock.close.assert_not_called()

    def test_a_different_named_hub_identify_is_not_preempted(self) -> None:
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        reconciliation = _make_reconciliation(listener, scenes)
        first, second = _mock_sock(10), _mock_sock(20)
        listener.clients.extend([first, second])
        listener.fd_to_client[10] = first
        listener.fd_to_client[20] = second

        reconciliation.handle_connect(first, ConnectMessage(name="a", kind="hub"))
        reconciliation.handle_connect(second, ConnectMessage(name="b", kind="hub"))

        first.close.assert_not_called()
        assert listener.hub_fd_for("a") == 10
        assert listener.hub_fd_for("b") == 20

    def test_a_blank_name_is_ignored(self) -> None:
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        reconciliation = _make_reconciliation(listener, scenes)
        sock = _mock_sock(10)

        reconciliation.handle_connect(sock, ConnectMessage(name="   ", kind="hub"))

        assert 10 not in listener.client_names

    def test_a_test_kind_identify_logs_a_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Every use of the backdoor leaves a durable, grep-able trace."""
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        reconciliation = _make_reconciliation(listener, scenes)
        sock = _mock_sock(10)

        msg = ConnectMessage(name="probe", kind="test")
        with caplog.at_level("WARNING"):
            reconciliation.handle_connect(sock, msg)

        assert any(
            "test-kind connect" in r.message and "fd=10" in r.message
            for r in caplog.records
        )

    def test_a_hub_kind_identify_logs_no_test_kind_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        reconciliation = _make_reconciliation(listener, scenes)
        sock = _mock_sock(10)

        msg = ConnectMessage(name="lux-mcp", kind="hub")
        with caplog.at_level("WARNING"):
            reconciliation.handle_connect(sock, msg)

        assert not any("test-kind connect" in r.message for r in caplog.records)


def _identify_as_hub(listener: SocketListener, fd: int) -> None:
    """Register ``fd`` as the hub identity a manifest must come from."""
    listener.register_client_identity(fd, kind="hub", name="lux-mcp", connect_time=0.0)


class TestHandleManifest:
    """Manifest receipt purges every scene not owned by fd and not manifested."""

    def test_a_scene_outside_the_manifest_is_purged(self) -> None:
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        scenes.handle_framed_scene(_make_scene("s1", "f1"), owner_fd=10)
        closed: list[str] = []
        reconciliation = _make_reconciliation(listener, scenes, closed.append)
        sock = _mock_sock(20)
        _identify_as_hub(listener, 20)

        reconciliation.handle_manifest(sock, HubManifestMessage(scene_ids=()))

        assert scenes.resolve_scene("s1") is None
        assert closed == ["f1"]

    def test_a_scene_in_the_manifest_survives(self) -> None:
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        scenes.handle_framed_scene(_make_scene("s1", "f1"), owner_fd=10)
        closed: list[str] = []
        reconciliation = _make_reconciliation(listener, scenes, closed.append)
        sock = _mock_sock(20)
        _identify_as_hub(listener, 20)

        reconciliation.handle_manifest(sock, HubManifestMessage(scene_ids=("s1",)))

        assert scenes.resolve_scene("s1") is not None
        assert closed == []

    def test_a_scene_owned_by_the_identifying_fd_survives(self) -> None:
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        scenes.handle_framed_scene(_make_scene("s1", "f1"), owner_fd=20)
        closed: list[str] = []
        reconciliation = _make_reconciliation(listener, scenes, closed.append)
        sock = _mock_sock(20)
        _identify_as_hub(listener, 20)

        reconciliation.handle_manifest(sock, HubManifestMessage(scene_ids=()))

        assert scenes.resolve_scene("s1") is not None
        assert closed == []

    def test_a_mixed_frame_only_loses_its_ghost_scene(self) -> None:
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        scenes.handle_framed_scene(_make_scene("s1", "f1"), owner_fd=10)
        scenes.handle_framed_scene(_make_scene("s2", "f1"), owner_fd=10)
        closed: list[str] = []
        reconciliation = _make_reconciliation(listener, scenes, closed.append)
        sock = _mock_sock(20)
        _identify_as_hub(listener, 20)

        reconciliation.handle_manifest(sock, HubManifestMessage(scene_ids=("s1",)))

        assert scenes.resolve_scene("s1") is not None
        assert scenes.resolve_scene("s2") is None

    def test_a_manifest_from_a_test_kind_fd_is_rejected_and_nothing_is_purged(
        self,
    ) -> None:
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        scenes.handle_framed_scene(_make_scene("s1", "f1"), owner_fd=10)
        closed: list[str] = []
        reconciliation = _make_reconciliation(listener, scenes, closed.append)
        sock = _mock_sock(20)
        listener.register_client_identity(
            20, kind="test", name="probe", connect_time=0.0
        )

        reconciliation.handle_manifest(sock, HubManifestMessage(scene_ids=()))

        assert scenes.resolve_scene("s1") is not None  # untouched
        assert closed == []

    def test_a_manifest_from_an_unidentified_fd_is_rejected(self) -> None:
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        scenes.handle_framed_scene(_make_scene("s1", "f1"), owner_fd=10)
        closed: list[str] = []
        reconciliation = _make_reconciliation(listener, scenes, closed.append)
        sock = _mock_sock(20)  # never sent a ConnectMessage at all

        reconciliation.handle_manifest(sock, HubManifestMessage(scene_ids=()))

        assert scenes.resolve_scene("s1") is not None
        assert closed == []

    def test_a_rejected_manifest_surfaces_via_the_injected_record_error(self) -> None:
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        errors: list[str] = []
        reconciliation = HubReconciliation(
            listener,
            scenes,
            lambda _fid: None,
            lambda _sev, msg, _ctx: errors.append(msg),
        )
        sock = _mock_sock(20)

        reconciliation.handle_manifest(sock, HubManifestMessage(scene_ids=()))

        assert any("HubManifestMessage" in m for m in errors)
