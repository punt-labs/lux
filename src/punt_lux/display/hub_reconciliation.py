"""Single-owner Hub-identity preemption and manifest-driven purge (DES-068).

Killing and restarting ``luxd`` drops its in-memory scene store; without this,
the Display keeps rendering the dead process's scenes forever, since nothing
ever tells it to stop. A ``kind="hub"`` connection declares its complete
scene manifest immediately after identifying, and this class is the policy
that reconciles the Display's replica against it: at most one connection may
hold the Hub's identity at a time (preemption), and every scene the manifest
disowns is purged, not just the ones the manifest happens to mention.
"""

from __future__ import annotations

import logging
import socket
import time
from typing import TYPE_CHECKING, Self

from punt_lux.socket_owner import SocketOwner

if TYPE_CHECKING:
    from collections.abc import Callable

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
    fresh manifest no longer claims (``handle_manifest``). Both read and
    mutate the injected ``SceneReplica`` and ``SocketListener`` directly —
    the same collaborators ``RenderLoop`` itself would have reached through —
    so this is decomposition, not a new layer of indirection.
    """

    _socket_listener: SocketListener
    _scenes: SceneReplica
    _record_error: _RecordError

    def __new__(
        cls,
        socket_listener: SocketListener,
        scenes: SceneReplica,
        record_error: _RecordError,
    ) -> Self:
        self = super().__new__(cls)
        self._socket_listener = socket_listener
        self._scenes = scenes
        self._record_error = record_error
        return self

    def handle_connect(self, sock: socket.socket, msg: ConnectMessage) -> None:
        """Record a client's declared identity (idempotent); preempt a stale Hub."""
        name = msg.name.strip()
        if not name:
            logger.warning("ConnectMessage with empty name -- ignored")
            return
        try:
            fd = sock.fileno()
        except OSError:
            return
        if msg.kind == "hub":
            self._preempt_stale_hub(fd, name)
        else:
            pid = SocketOwner.peer_pid_of(sock)
            logger.warning(
                "test-kind connect: fd=%d pid=%s name=%r "
                "-- read-only path; not a supported production mode",
                fd,
                pid if pid is not None else "?",
                name,
            )
            self._record_error(
                "warning", f"test-kind connect fd={fd} name={name!r}", "connect"
            )
        self._socket_listener.register_client_identity(
            fd, kind=msg.kind, name=name, connect_time=time.time()
        )
        logger.info("Client fd=%d identified as %r (kind=%s)", fd, name, msg.kind)

    def handle_manifest(self, sock: socket.socket, msg: HubManifestMessage) -> None:
        """Purge every scene the manifest disowns, disposing any frame it empties.

        Only a ``kind="hub"`` fd may declare a manifest — a ``"test"`` fd or one
        that never identified is rejected and nothing is purged, since the whole
        point of a manifest is that its sender is the one process the Display
        trusts to say what the Hub currently holds.

        A scene qualifies for purge when it is neither owned by the identifying
        fd nor named in the manifest — orphaned scenes from a prior Hub die are
        swept by the same rule, since their owner is never this fd.

        A purge is a content event: the Hub is saying the scene is gone, so an
        emptied frame is *disposed*, whatever visibility the user had left it in.
        A frame with no content is a husk, and a closed one is no exception.
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
        for frame_id, scene_id in self._scenes.scenes_to_purge(fd, manifest):
            frame = self._scenes.frames.get(frame_id)
            if frame is None:
                continue
            if self._scenes.dismiss_framed_scene(frame, scene_id):
                self._scenes.dispose_frame(frame_id)

    def reject_scene_if_test_kind(self, sock: socket.socket, fd: int) -> bool:
        """Reject a ``SceneMessage`` from a ``kind="test"`` fd; close it.

        A ``"test"`` connection may observe, never install. Returns ``True``
        when the caller must stop processing this message (rejected and the
        fd is gone); ``False`` for every ordinary fd, identified or not.
        """
        if self._socket_listener.kind_of(fd) != "test":
            return False
        logger.warning(
            "test-kind fd=%d attempted SceneMessage; rejecting and closing", fd
        )
        self._record_error(
            "error", f"test-kind connection (fd={fd}) attempted a SceneMessage", ""
        )
        self._socket_listener.remove_client(sock)
        return True

    def _preempt_stale_hub(self, fd: int, name: str) -> None:
        """Force-disconnect any other live connection already declaring this identity.

        Runs before the new identify is recorded, so at most one connection ever
        holds ``kind="hub", name`` at a time — closing the interleaving where a
        straggling message from a superseded connection could re-materialize a
        scene a fresh manifest just purged.
        """
        stale_fd = self._socket_listener.hub_fd_for(name)
        if stale_fd is None or stale_fd == fd:
            return
        stale_sock = self._socket_listener.fd_to_client.get(stale_fd)
        if stale_sock is not None:
            logger.info("Preempting stale hub connection fd=%d for %r", stale_fd, name)
            self._socket_listener.remove_client(stale_sock)
