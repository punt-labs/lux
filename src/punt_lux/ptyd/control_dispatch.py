"""Control operations over authenticated local terminal connections."""

from __future__ import annotations

import logging
from typing import Self

from punt_lux.protocol.pty.control import (
    WIRE_VERSION,
    AttachRequest,
    HelloRequest,
    KillRequest,
    ListRequest,
    Request,
)
from punt_lux.ptyd import snapshot as _snapshots
from punt_lux.ptyd.core import SessionCore
from punt_lux.ptyd.peer import Peer
from punt_lux.ptyd.snapshot_cut import SnapshotCut
from punt_lux.ptyd.stream_output import StreamPublisher
from punt_lux.ptyd.viewers import ViewerBindings

logger = logging.getLogger(__name__)


class ControlDispatch:
    """Negotiate, create/attach, inspect and explicitly terminate sessions."""

    _core: SessionCore
    _bindings: ViewerBindings

    def __new__(cls, core: SessionCore, bindings: ViewerBindings) -> Self:
        self = super().__new__(cls)
        self._core, self._bindings = core, bindings
        return self

    def execute(self, peer: Peer, request: Request) -> None:
        if isinstance(request, HelloRequest):
            self._hello(peer, request)
        elif not peer.ready:
            raise ValueError("hello must precede session requests")
        elif isinstance(request, AttachRequest):
            self._attach(peer, request)
        elif isinstance(request, ListRequest):
            StreamPublisher.success(
                peer, request.request_id, {"sessions": self._core.describe()}
            )
        elif isinstance(request, KillRequest):
            self._bindings.close_session(request.session, "session killed")
            self._core.kill(request.session)
            StreamPublisher.success(peer, request.request_id, {})
        else:
            # new and watch decode on the wire but the daemon does not act on
            # them yet; refuse them rather than run them as something else.
            StreamPublisher.failure(
                peer, request.request_id, f"unsupported operation {request.OP}"
            )

    @staticmethod
    def _hello(peer: Peer, request: HelloRequest) -> None:
        expected = (WIRE_VERSION, _snapshots.snapshot_version())
        if (request.version, request.snapshot_version) != expected:
            raise ValueError("protocol/snapshot mismatch; restart client and daemon")
        peer.mark_ready()
        StreamPublisher.success(
            peer,
            request.request_id,
            {"version": expected[0], "snapshot_version": expected[1]},
        )

    def _attach(self, peer: Peer, request: AttachRequest) -> None:
        session = self._core.acquire(request)
        if not self._bindings.session(request.session):
            self._core.resize(request.session, request.cols, request.rows)
        try:
            snapshot = SnapshotCut(session).cut()
        except _snapshots.SnapshotError:
            # Fail this request only: the connection carries every terminal the
            # Display shows, and the client retries with backoff.
            logger.warning(
                "terminal %s: attach failed, no snapshot can be cut",
                request.session,
                exc_info=True,
            )
            raise
        binding = self._bindings.add(peer, request.session, request.cols, request.rows)
        StreamPublisher.attach(
            binding, request.request_id, snapshot, session.describe()
        )
