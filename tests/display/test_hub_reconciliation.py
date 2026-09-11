"""HubReconciliation — single-owner Hub preemption and manifest purge (DES-068).

Pure unit tests against a real ``SocketListener`` and ``SceneReplica`` with
faked sockets — no ImGui, no real subprocess. The harness/subprocess test
that exercises the real wire protocol end to end lives in
``tests/integration/test_hub_display_reconciliation.py``.
"""

from __future__ import annotations

import ssl
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

from punt_lux.display.hub_reconciliation import HubReconciliation
from punt_lux.display.identity_guard import IdentityGuard
from punt_lux.display.replica import SceneReplica
from punt_lux.display.socket_listener_callbacks import SocketListenerCallbacks
from punt_lux.display.socket_server import SocketListener
from punt_lux.domain.identity import HubId
from punt_lux.protocol import (
    ConnectMessage,
    HubManifestMessage,
    SceneMessage,
    TextElement,
)
from punt_lux.trust import CertificateAuthority

_HUB_A = HubId("hub-a.invalid", 1)
_HUB_B = HubId("hub-b.invalid", 2)
_HUB_C = HubId("hub-c.invalid", 3)

if TYPE_CHECKING:
    import pytest


def _mock_sock(fd: int) -> MagicMock:
    sock = MagicMock()
    sock.fileno.return_value = fd
    return sock


def _make_listener() -> SocketListener:
    return SocketListener(
        SocketListenerCallbacks(
            on_message=lambda _sock, _msg: None,
            on_client_disconnected=lambda _fd: None,
            on_error=lambda _sev, _msg, _ctx: None,
        )
    )


def _noop_record_error(_sev: str, _msg: str, _ctx: str) -> None:
    return None


def _make_reconciliation(
    listener: SocketListener,
    scenes: SceneReplica,
) -> HubReconciliation:
    return HubReconciliation(
        listener,
        scenes,
        _noop_record_error,
        IdentityGuard(listener, _noop_record_error),
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

        reconciliation.handle_connect(
            sock, ConnectMessage(name="lux-mcp", kind="hub", hub_id="pembroke\x1f123")
        )

        assert listener.hub_fd_for(HubId("pembroke", 123)) == 10

    def test_a_test_identify_never_preempts_or_marks_hub(self) -> None:
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        reconciliation = _make_reconciliation(listener, scenes)
        sock = _mock_sock(10)

        probe = ConnectMessage(name="quarry", kind="test", hub_id="test.invalid\x1f0")
        reconciliation.handle_connect(sock, probe)

        assert listener.hub_fd_for(HubId("test.invalid", 0)) is None
        assert listener.client_names[10] == "quarry"
        assert listener.kind_of(10) == "test"

    def test_a_second_hub_identify_forcibly_disconnects_the_first(self) -> None:
        """A reconnect under the *same* HubId preempts its own predecessor."""
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        reconciliation = _make_reconciliation(listener, scenes)
        old_sock, new_sock = _mock_sock(10), _mock_sock(20)
        listener.clients.append(old_sock)
        listener.fd_to_client[10] = old_sock

        reconciliation.handle_connect(
            old_sock,
            ConnectMessage(name="lux-mcp", kind="hub", hub_id="pembroke\x1f123"),
        )
        assert listener.hub_fd_for(HubId("pembroke", 123)) == 10

        listener.clients.append(new_sock)
        listener.fd_to_client[20] = new_sock
        reconciliation.handle_connect(
            new_sock,
            ConnectMessage(name="lux-mcp", kind="hub", hub_id="pembroke\x1f123"),
        )

        old_sock.close.assert_called_once()  # forcibly removed
        assert old_sock not in listener.clients
        # the new claimant, and only it
        assert listener.hub_fd_for(HubId("pembroke", 123)) == 20

    def test_a_hub_identify_with_no_predecessor_preempts_nothing(self) -> None:
        """The ordinary restart case: the old process's socket is already gone."""
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        reconciliation = _make_reconciliation(listener, scenes)
        sock = _mock_sock(10)

        reconciliation.handle_connect(
            sock, ConnectMessage(name="lux-mcp", kind="hub", hub_id="pembroke\x1f123")
        )

        sock.close.assert_not_called()

    def test_a_different_hub_id_identify_is_not_preempted(self) -> None:
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        reconciliation = _make_reconciliation(listener, scenes)
        first, second = _mock_sock(10), _mock_sock(20)
        listener.clients.extend([first, second])
        listener.fd_to_client[10] = first
        listener.fd_to_client[20] = second

        reconciliation.handle_connect(
            first, ConnectMessage(name="a", kind="hub", hub_id="a.example\x1f1")
        )
        reconciliation.handle_connect(
            second, ConnectMessage(name="b", kind="hub", hub_id="b.example\x1f2")
        )

        first.close.assert_not_called()
        assert listener.hub_fd_for(HubId("a.example", 1)) == 10
        assert listener.hub_fd_for(HubId("b.example", 2)) == 20

    def test_two_hub_ids_sharing_the_same_name_both_stay_connected(self) -> None:
        """W11: preemption keys on HubId, never the declared name -- every
        production Hub today declares the identical hardcoded name
        (``_DISPLAY_CLIENT_NAME``), so two genuinely distinct Hubs sharing
        that name must coexist rather than preempt one another."""
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        reconciliation = _make_reconciliation(listener, scenes)
        first, second = _mock_sock(10), _mock_sock(20)
        listener.clients.extend([first, second])
        listener.fd_to_client[10] = first
        listener.fd_to_client[20] = second

        reconciliation.handle_connect(
            first, ConnectMessage(name="lux-mcp", kind="hub", hub_id="pembroke\x1f123")
        )
        reconciliation.handle_connect(
            second, ConnectMessage(name="lux-mcp", kind="hub", hub_id="orsett\x1f456")
        )

        first.close.assert_not_called()
        assert first in listener.clients
        assert second in listener.clients
        assert listener.hub_fd_for(HubId("pembroke", 123)) == 10
        assert listener.hub_fd_for(HubId("orsett", 456)) == 20

    def test_a_reconnect_under_a_different_name_but_same_hub_id_still_preempts(
        self,
    ) -> None:
        """The declared name plays no role in preemption after W11 -- only
        the HubId identifies "the same process reconnecting"."""
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        reconciliation = _make_reconciliation(listener, scenes)
        old_sock, new_sock = _mock_sock(10), _mock_sock(20)
        listener.clients.append(old_sock)
        listener.fd_to_client[10] = old_sock

        reconciliation.handle_connect(
            old_sock,
            ConnectMessage(name="lux-mcp", kind="hub", hub_id="pembroke\x1f123"),
        )
        listener.clients.append(new_sock)
        listener.fd_to_client[20] = new_sock
        reconciliation.handle_connect(
            new_sock,
            ConnectMessage(
                name="a-different-display-name", kind="hub", hub_id="pembroke\x1f123"
            ),
        )

        old_sock.close.assert_called_once()  # preempted despite the new name
        assert listener.hub_fd_for(HubId("pembroke", 123)) == 20

    def test_a_blank_name_is_ignored(self) -> None:
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        reconciliation = _make_reconciliation(listener, scenes)
        sock = _mock_sock(10)

        reconciliation.handle_connect(
            sock, ConnectMessage(name="   ", kind="hub", hub_id="pembroke\x1f123")
        )

        assert 10 not in listener.client_names

    def test_a_test_kind_identify_logs_a_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Every use of the backdoor leaves a durable, grep-able trace."""
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        reconciliation = _make_reconciliation(listener, scenes)
        sock = _mock_sock(10)

        msg = ConnectMessage(name="probe", kind="test", hub_id="test.invalid\x1f0")
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

        msg = ConnectMessage(name="lux-mcp", kind="hub", hub_id="pembroke\x1f123")
        with caplog.at_level("WARNING"):
            reconciliation.handle_connect(sock, msg)

        assert not any("test-kind connect" in r.message for r in caplog.records)


def _der_for(hostname: str) -> bytes:
    """Return DER bytes for a freshly-issued leaf naming *hostname* (W7 material)."""
    ca = CertificateAuthority.create()
    _, leaf = ca.issue_leaf(hostname)
    return leaf.to_der()


def _ssl_mock_sock(fd: int, der: bytes) -> MagicMock:
    """A ``MagicMock(spec=ssl.SSLSocket)`` -- the cross-host (TLS) shape,
    distinguishable from :func:`_mock_sock`'s plain ``AF_UNIX`` shape by
    ``isinstance``, exactly as :class:`CrossHostVerification` distinguishes
    them."""
    sock = MagicMock(spec=ssl.SSLSocket)
    sock.fileno.return_value = fd
    sock.getpeercert.return_value = der
    return sock


class TestCrossHostHostnameVerification:
    """Gate 2 (system.tex §"Coexistence with the Local Fast Path"): a
    cross-host peer's declared ``hub_id.hostname`` must match its mTLS
    certificate's SAN before ``handle_connect`` will identify it."""

    def test_a_matching_hostname_is_identified_normally(self) -> None:
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        reconciliation = _make_reconciliation(listener, scenes)
        sock = _ssl_mock_sock(10, _der_for("hub7.example.com"))

        reconciliation.handle_connect(
            sock,
            ConnectMessage(
                name="lux-mcp", kind="hub", hub_id="hub7.example.com\x1f123"
            ),
        )

        assert listener.hub_fd_for(HubId("hub7.example.com", 123)) == 10
        sock.close.assert_not_called()

    def test_a_mismatched_hostname_is_rejected_closed_and_never_identified(
        self,
    ) -> None:
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        reconciliation = _make_reconciliation(listener, scenes)
        sock = _ssl_mock_sock(10, _der_for("hub7.example.com"))
        listener.clients.append(sock)
        listener.fd_to_client[10] = sock

        reconciliation.handle_connect(
            sock,
            ConnectMessage(
                name="lux-mcp", kind="hub", hub_id="attacker.example.com\x1f123"
            ),
        )

        assert listener.hub_fd_for(HubId("attacker.example.com", 123)) is None
        assert listener.kind_of(10) is None  # never identified
        sock.close.assert_called_once()
        assert sock not in listener.clients

    def test_a_mismatch_is_never_preempted_as_a_stale_hub(self) -> None:
        """A rejected connect must not reach preemption -- there is nothing
        legitimate to preempt on behalf of an unverified declaration."""
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        reconciliation = _make_reconciliation(listener, scenes)
        live = _mock_sock(10)
        listener.register_client_identity(
            10,
            kind="hub",
            name="lux-mcp",
            connect_time=0.0,
            hub_id=HubId("pembroke", 123),
        )
        listener.clients.append(live)
        mismatched = _ssl_mock_sock(20, _der_for("hub7.example.com"))
        listener.clients.append(mismatched)
        listener.fd_to_client[20] = mismatched

        reconciliation.handle_connect(
            mismatched,
            ConnectMessage(name="lux-mcp", kind="hub", hub_id="pembroke\x1f123"),
        )

        live.close.assert_not_called()  # the live, unrelated hub survives
        assert listener.hub_fd_for(HubId("pembroke", 123)) == 10

    def test_a_mismatch_surfaces_via_the_injected_record_error(self) -> None:
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        errors: list[str] = []

        def record_error(_sev: str, msg: str, _ctx: str) -> None:
            errors.append(msg)

        reconciliation = HubReconciliation(
            listener, scenes, record_error, IdentityGuard(listener, record_error)
        )
        sock = _ssl_mock_sock(10, _der_for("hub7.example.com"))

        reconciliation.handle_connect(
            sock,
            ConnectMessage(
                name="lux-mcp", kind="hub", hub_id="attacker.example.com\x1f123"
            ),
        )

        assert any("hostname verification failed" in m for m in errors)

    def test_a_same_host_af_unix_connect_is_unaffected(self) -> None:
        """Invariant 4: a plain (non-TLS) socket is never subject to this
        gate, whatever hostname its ``hub_id`` declares."""
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        reconciliation = _make_reconciliation(listener, scenes)
        sock = _mock_sock(10)  # plain MagicMock -- not ssl.SSLSocket

        reconciliation.handle_connect(
            sock,
            ConnectMessage(
                name="lux-mcp", kind="hub", hub_id="anything.invalid\x1f123"
            ),
        )

        assert listener.hub_fd_for(HubId("anything.invalid", 123)) == 10
        sock.close.assert_not_called()

    def test_a_reconnect_differing_only_in_declared_hostname_case_preempts(
        self,
    ) -> None:
        """The identity/preemption bypass this gate exists to close: a peer
        declaring ``HUB1.EXAMPLE.COM`` is the *same* HubId as one already
        live under ``hub1.example.com`` -- it must preempt, not coexist as
        a second, distinct identity (W11's at-most-one-per-HubId)."""
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        reconciliation = _make_reconciliation(listener, scenes)
        old_sock = _ssl_mock_sock(10, _der_for("hub1.example.com"))
        listener.clients.append(old_sock)
        listener.fd_to_client[10] = old_sock
        reconciliation.handle_connect(
            old_sock,
            ConnectMessage(
                name="lux-mcp", kind="hub", hub_id="hub1.example.com\x1f123"
            ),
        )
        assert listener.hub_fd_for(HubId("hub1.example.com", 123)) == 10

        new_sock = _ssl_mock_sock(20, _der_for("hub1.example.com"))
        listener.clients.append(new_sock)
        listener.fd_to_client[20] = new_sock
        reconciliation.handle_connect(
            new_sock,
            ConnectMessage(
                name="lux-mcp", kind="hub", hub_id="HUB1.EXAMPLE.COM\x1f123"
            ),
        )

        old_sock.close.assert_called_once()  # preempted, not left coexisting
        assert old_sock not in listener.clients
        assert listener.hub_fd_for(HubId("hub1.example.com", 123)) == 20
        assert listener.hub_fd_for(HubId("HUB1.EXAMPLE.COM", 123)) == 20


class TestCrossHostTestKindRefused:
    """T6 (system.tex §"Connect, cross-host"): the ``kind="test"`` backdoor's
    safety rests on the ``AF_UNIX`` socket's ``0700`` permission, which does
    not carry across a network -- so a TLS peer declaring it is refused."""

    _STUB_TOKEN = HubId.stub().wire_token

    def test_a_cross_host_test_kind_connect_is_rejected_closed_and_unidentified(
        self,
    ) -> None:
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        reconciliation = _make_reconciliation(listener, scenes)
        sock = _ssl_mock_sock(10, _der_for("hub7.example.com"))
        listener.clients.append(sock)
        listener.fd_to_client[10] = sock

        reconciliation.handle_connect(
            sock, ConnectMessage(name="probe", kind="test", hub_id=self._STUB_TOKEN)
        )

        assert listener.kind_of(10) is None  # never identified
        sock.close.assert_called_once()
        assert sock not in listener.clients

    def test_a_same_host_test_kind_connect_is_still_admitted(self) -> None:
        """The gate is scoped to TLS sockets: a plain ``AF_UNIX`` test probe
        (the local development backdoor) still identifies normally."""
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        reconciliation = _make_reconciliation(listener, scenes)
        sock = _mock_sock(10)  # plain MagicMock -- not ssl.SSLSocket

        reconciliation.handle_connect(
            sock, ConnectMessage(name="probe", kind="test", hub_id=self._STUB_TOKEN)
        )

        assert listener.kind_of(10) == "test"
        sock.close.assert_not_called()


def _identify_as_hub(listener: SocketListener, sock: MagicMock) -> None:
    """Register ``sock`` as an identified, connected ``kind="hub"`` fd --
    live, not merely identified, so :meth:`HubReconciliation._live_hubs`
    (which walks ``listener.clients``) sees it exactly as a real connect
    would leave it."""
    listener.register_client_identity(
        sock.fileno(), kind="hub", name="lux-mcp", connect_time=0.0
    )
    listener.clients.append(sock)


class TestHandleManifest:
    """Manifest receipt purges every scene not owned by fd and not manifested."""

    def test_a_scene_outside_the_manifest_is_purged(self) -> None:
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        scenes.handle_framed_scene(_make_scene("s1", "f1"), owner_fd=10)
        reconciliation = _make_reconciliation(listener, scenes)
        sock = _mock_sock(20)
        _identify_as_hub(listener, sock)

        reconciliation.handle_manifest(sock, HubManifestMessage(scene_ids=()))

        assert scenes.resolve_scene("s1") is None
        assert "f1" not in scenes.frames  # the pass emptied it, so the husk goes too

    def test_a_scene_in_the_manifest_survives(self) -> None:
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        scenes.handle_framed_scene(_make_scene("s1", "f1"), owner_fd=10)
        reconciliation = _make_reconciliation(listener, scenes)
        sock = _mock_sock(20)
        _identify_as_hub(listener, sock)

        reconciliation.handle_manifest(sock, HubManifestMessage(scene_ids=("s1",)))

        assert scenes.resolve_scene("s1") is not None
        assert "f1" in scenes.frames

    def test_an_empty_manifest_purges_even_the_senders_own_just_pushed_scene(
        self,
    ) -> None:
        """The manifest is authoritative: it disowns whatever it omits, full
        stop -- a scene surviving only because it shares the sending
        connection's fd would undermine that authority."""
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        scenes.handle_framed_scene(_make_scene("s1", "f1"), owner_fd=20)
        reconciliation = _make_reconciliation(listener, scenes)
        sock = _mock_sock(20)
        _identify_as_hub(listener, sock)

        reconciliation.handle_manifest(sock, HubManifestMessage(scene_ids=()))

        assert scenes.resolve_scene("s1") is None
        assert "f1" not in scenes.frames

    def test_a_still_live_different_hubs_scene_is_never_purged(self) -> None:
        """The collision-safe property: Hub A's manifest never disowns Hub B's,
        even sharing a local scene id, as long as Hub B is still connected."""
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        scenes.handle_framed_scene(_make_scene("s1", "fA"), owner_fd=10, hub=_HUB_A)
        scenes.handle_framed_scene(_make_scene("s1", "fB"), owner_fd=11, hub=_HUB_B)
        reconciliation = _make_reconciliation(listener, scenes)
        sock_a = _mock_sock(10)
        sock_b = _mock_sock(11)
        listener.register_client_identity(
            10, kind="hub", name="lux-mcp", connect_time=0.0, hub_id=_HUB_A
        )
        listener.register_client_identity(
            11, kind="hub", name="lux-mcp", connect_time=0.0, hub_id=_HUB_B
        )
        listener._clients.extend([sock_a, sock_b])  # test harness reaches in directly

        reconciliation.handle_manifest(sock_a, HubManifestMessage(scene_ids=()))

        assert scenes.resolve_scene("s1") is not None  # Hub B's survives
        assert "fB" in scenes.frames
        assert "fA" not in scenes.frames  # Hub A's own was purged

    def test_own_purge_live_survival_and_orphan_sweep_compose_end_to_end(self) -> None:
        """The full manifest-application path, in one reconciliation: Hub
        A's own omitted scene is purged, Hub B's still-live scene survives
        untouched, and Hub C's scene -- never connected here, an orphan --
        is swept, confirming the manifest applies strictly within the
        sender's own Hub scope."""
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        scenes.handle_framed_scene(_make_scene("s1", "fA"), owner_fd=10, hub=_HUB_A)
        scenes.handle_framed_scene(_make_scene("s1", "fB"), owner_fd=11, hub=_HUB_B)
        scenes.handle_framed_scene(_make_scene("s1", "fC"), owner_fd=12, hub=_HUB_C)
        reconciliation = _make_reconciliation(listener, scenes)
        sock_a = _mock_sock(10)
        sock_b = _mock_sock(11)
        listener.register_client_identity(
            10, kind="hub", name="lux-mcp", connect_time=0.0, hub_id=_HUB_A
        )
        listener.register_client_identity(
            11, kind="hub", name="lux-mcp", connect_time=0.0, hub_id=_HUB_B
        )
        listener._clients.extend([sock_a, sock_b])  # Hub C never connects -- an orphan

        reconciliation.handle_manifest(sock_a, HubManifestMessage(scene_ids=()))

        assert "fA" not in scenes.frames  # A's own omitted scene, purged
        assert "fB" in scenes.frames  # B's still-live scene, untouched
        assert "fC" not in scenes.frames  # C's orphaned scene, swept

    def test_a_mixed_frame_only_loses_its_ghost_scene(self) -> None:
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        scenes.handle_framed_scene(_make_scene("s1", "f1"), owner_fd=10)
        scenes.handle_framed_scene(_make_scene("s2", "f1"), owner_fd=10)
        reconciliation = _make_reconciliation(listener, scenes)
        sock = _mock_sock(20)
        _identify_as_hub(listener, sock)

        reconciliation.handle_manifest(sock, HubManifestMessage(scene_ids=("s1",)))

        assert scenes.resolve_scene("s1") is not None
        assert scenes.resolve_scene("s2") is None

    def test_a_manifest_from_a_test_kind_fd_is_rejected_and_nothing_is_purged(
        self,
    ) -> None:
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        scenes.handle_framed_scene(_make_scene("s1", "f1"), owner_fd=10)
        reconciliation = _make_reconciliation(listener, scenes)
        sock = _mock_sock(20)
        listener.register_client_identity(
            20, kind="test", name="probe", connect_time=0.0
        )

        reconciliation.handle_manifest(sock, HubManifestMessage(scene_ids=()))

        assert scenes.resolve_scene("s1") is not None  # untouched
        assert "f1" in scenes.frames

    def test_a_manifest_from_an_unidentified_fd_is_rejected(self) -> None:
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        scenes.handle_framed_scene(_make_scene("s1", "f1"), owner_fd=10)
        reconciliation = _make_reconciliation(listener, scenes)
        sock = _mock_sock(20)  # never sent a ConnectMessage at all

        reconciliation.handle_manifest(sock, HubManifestMessage(scene_ids=()))

        assert scenes.resolve_scene("s1") is not None
        assert "f1" in scenes.frames

    def test_a_rejected_manifest_surfaces_via_the_injected_record_error(self) -> None:
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        errors: list[str] = []

        def record_error(_sev: str, msg: str, _ctx: str) -> None:
            errors.append(msg)

        reconciliation = HubReconciliation(
            listener, scenes, record_error, IdentityGuard(listener, record_error)
        )
        sock = _mock_sock(20)

        reconciliation.handle_manifest(sock, HubManifestMessage(scene_ids=()))

        assert any("HubManifestMessage" in m for m in errors)


class TestRejectSceneUnlessHub:
    """A ``SceneMessage`` installs only once the fd has identified as ``"hub"``.

    An fd that never sent a ``ConnectMessage`` (``kind_of(fd) is None``) is
    rejected exactly like the already-rejected ``kind="test"`` observer.
    Full None/test/hub boundary and the dead-socket case live in
    ``test_identity_guard.py``, which this class's delegate defers to; these
    tests confirm the wiring, not the policy.
    """

    def test_an_unidentified_fd_is_rejected_and_closed(self) -> None:
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        reconciliation = _make_reconciliation(listener, scenes)
        sock = _mock_sock(10)
        listener.clients.append(sock)
        listener.fd_to_client[10] = sock

        rejected = reconciliation.reject_scene_unless_hub(sock)

        assert rejected is True
        sock.close.assert_called_once()
        assert sock not in listener.clients

    def test_a_hub_kind_fd_is_not_rejected(self) -> None:
        listener = _make_listener()
        scenes = SceneReplica(on_scene_replaced=lambda _ids: None)
        reconciliation = _make_reconciliation(listener, scenes)
        sock = _mock_sock(10)
        listener.register_client_identity(
            10, kind="hub", name="lux-mcp", connect_time=0.0
        )

        rejected = reconciliation.reject_scene_unless_hub(sock)

        assert rejected is False
        sock.close.assert_not_called()
