"""Single-owner Hub-identity preemption and manifest-driven purge (DES-068).

A ``kind="hub"`` connection declares its manifest right after identifying,
and this class reconciles the Display's replica against it.
"""

from __future__ import annotations

import logging
import socket
import ssl
import time
from typing import TYPE_CHECKING, Self

from punt_lux.display.cross_host_verification import CrossHostVerification
from punt_lux.domain.identity import HubId, HubIdToken
from punt_lux.socket_owner import SocketOwner

if TYPE_CHECKING:
    from collections.abc import Callable

    from punt_lux.display.identity_guard import IdentityGuard
    from punt_lux.display.replica import SceneReplica
    from punt_lux.display.socket_server import SocketListener
    from punt_lux.protocol import ConnectMessage, HubManifestMessage

    _RecordError = Callable[[str, str, str], None]

logger = logging.getLogger(__name__)

__all__ = ["HubReconciliation"]


class HubReconciliation:
    """Composed by ``RenderLoop`` so its socket-callback dispatch stays thin.

    Owns two DES-068 responsibilities: forcing a stale Hub-kind connection off
    before recording a new one (``handle_connect``), and purging every scene a
    fresh manifest no longer claims (``handle_manifest``). Both mutate the
    injected ``SceneReplica`` and ``SocketListener`` directly -- decomposition,
    not a new layer of indirection.
    """

    _socket_listener: SocketListener
    _scenes: SceneReplica
    _record_error: _RecordError
    _identity: IdentityGuard
    _cross_host: CrossHostVerification

    def __new__(
        cls,
        socket_listener: SocketListener,
        scenes: SceneReplica,
        record_error: _RecordError,
        identity: IdentityGuard,
    ) -> Self:
        self = super().__new__(cls)
        self._socket_listener = socket_listener
        self._scenes = scenes
        self._record_error = record_error
        self._identity = identity
        self._cross_host = CrossHostVerification()
        return self

    def handle_connect(self, sock: socket.socket, msg: ConnectMessage) -> None:
        """Record a client's declared identity (idempotent); preempt a stale Hub.

        Two cross-host gates run first, both closing the connection before it
        can become an identified fd -- the state content-bearing messages
        require (Invariant 1). T6: a TLS peer may never declare ``kind="test"``.
        Gate 2: a TLS peer's declared ``hub_id`` must match the hostname its
        handshake verified. A same-host (``AF_UNIX``) connection is untouched by
        either (Invariant 4).
        """
        name = msg.name.strip()
        if not name:
            logger.warning("ConnectMessage with empty name -- ignored")
            return
        try:
            hub_id = HubIdToken(msg.hub_id).resolve()
        except ValueError:
            logger.warning("malformed hub_id=%r -- ignored", msg.hub_id)
            return
        try:
            fd = sock.fileno()
        except OSError:
            return
        if self._reject_test_kind_cross_host(sock, fd, msg):
            return
        if self._reject_unverified_cross_host(sock, fd, hub_id):
            return
        self._identify(sock, fd, msg, hub_id)

    def _reject_test_kind_cross_host(
        self, sock: socket.socket, fd: int, msg: ConnectMessage
    ) -> bool:
        """T6: close a cross-host (TLS) peer that declares ``kind="test"``.

        The test-kind backdoor's safety rests on the ``AF_UNIX`` socket's
        ``0700`` permission, an argument that does not carry across a network
        -- so a TLS connection declaring it is refused outright, never a
        read-only observer. A same-host connection is not a
        :class:`ssl.SSLSocket` and passes through.
        """
        if not isinstance(sock, ssl.SSLSocket) or msg.kind != "test":
            return False
        self._record_error(
            "error", f"cross-host test-kind connect refused (fd={fd})", "connect"
        )
        self._socket_listener.remove_client(sock)
        return True

    def _reject_unverified_cross_host(
        self, sock: socket.socket, fd: int, hub_id: HubId
    ) -> bool:
        """Gate 2: close and refuse to identify a SAN/``hub_id`` mismatch.

        A same-host connection is never rejected here -- see
        :class:`CrossHostVerification`.
        """
        if not self._cross_host.reject_unless_verified(sock, hub_id):
            return False
        self._record_error(
            "error",
            f"cross-host hostname verification failed (fd={fd}, "
            f"hub_id={hub_id.hostname!r})",
            "connect",
        )
        self._socket_listener.remove_client(sock)
        return True

    def _identify(
        self, sock: socket.socket, fd: int, msg: ConnectMessage, hub_id: HubId
    ) -> None:
        """Preempt a stale same-``HubId`` Hub, then record this fd's identity.

        ``msg.name`` arrives pre-validated non-blank by :meth:`handle_connect`
        -- re-stripped here rather than threaded through as a fifth
        parameter (PY-OO-3).
        """
        name = msg.name.strip()
        if msg.kind == "hub":
            self._preempt_stale_hub(fd, hub_id)
        else:
            self._log_test_kind_connect(sock, fd, name)
        self._socket_listener.register_client_identity(
            fd, kind=msg.kind, name=name, hub_id=hub_id, connect_time=time.time()
        )
        logger.info("Client fd=%d identified as %r (kind=%s)", fd, name, msg.kind)

    def _log_test_kind_connect(self, sock: socket.socket, fd: int, name: str) -> None:
        """Warn and record a read-only ``kind="test"`` identify."""
        pid = SocketOwner.peer_pid_of(sock)
        logger.warning("test-kind connect: fd=%d pid=%s name=%r", fd, pid, name)
        self._record_error(
            "warning", f"test-kind connect fd={fd} name={name!r}", "connect"
        )

    def handle_manifest(self, sock: socket.socket, msg: HubManifestMessage) -> None:
        """Purge every scene the manifest disowns, disposing any frame it empties.

        Only a ``kind="hub"`` fd may declare a manifest; see
        :meth:`SceneReplica.scenes_to_purge` for what qualifies for purge.
        """
        try:
            fd = sock.fileno()
        except OSError:
            return
        if self._socket_listener.kind_of(fd) != "hub":
            logger.warning("non-hub fd=%d sent HubManifestMessage; ignoring", fd)
            self._record_error(
                "error", f"non-hub connection (fd={fd}) sent HubManifestMessage", ""
            )
            return
        manifest = frozenset(msg.scene_ids)
        hub = self.hub_of(sock)
        purge = self._scenes.scenes_to_purge(hub, manifest, self._live_hubs())
        for frame_key, scene_id in purge:
            frame = self._scenes.frame(frame_key.local, frame_key.hub)
            if frame is None:
                continue
            if self._scenes.dismiss_framed_scene(frame, scene_id):
                self._scenes.dispose_frame(frame_key.local, frame_key.hub)

    def _live_hubs(self) -> frozenset[HubId]:
        """Return the ``HubId`` of every currently connected ``kind="hub"`` fd."""
        listener = self._socket_listener
        return frozenset(
            hub
            for sock in listener.clients
            if listener.kind_of(sock.fileno()) == "hub"
            and (hub := listener.hub_id_of(sock.fileno())) is not None
        )

    def reject_scene_unless_hub(self, sock: socket.socket) -> bool:
        """Reject a ``SceneMessage`` unless the fd has identified as ``"hub"``."""
        return self._identity.reject_scene_unless_hub(sock)

    def hub_of(self, sock: socket.socket) -> HubId:
        """Return the sender's ``HubId``; :meth:`HubId.stub` is the fallback."""
        hub = self._socket_listener.hub_id_of(sock.fileno())
        return hub if hub is not None else HubId.stub()

    def _preempt_stale_hub(self, fd: int, hub_id: HubId) -> None:
        """Force-disconnect any prior live connection declaring this ``HubId``.

        Keyed on ``HubId`` (W11), never on the declared ``name`` -- ``name``
        keeps its narrower "what a human calls this" meaning and plays no
        role in single-owner preemption. Two distinct Hubs sharing a name
        (every production Hub today declares the identical hardcoded name)
        coexist; only a reconnect under the *same* ``HubId`` preempts its own
        stale predecessor.
        """
        stale_fd = self._socket_listener.hub_fd_for(hub_id)
        if stale_fd is None or stale_fd == fd:
            return
        stale_sock = self._socket_listener.fd_to_client.get(stale_fd)
        if stale_sock is not None:
            logger.info(
                "Preempting stale hub connection fd=%d for hub_id=%r", stale_fd, hub_id
            )
            self._socket_listener.remove_client(stale_sock)
