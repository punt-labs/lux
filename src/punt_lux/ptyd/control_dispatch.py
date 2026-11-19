"""Control operations over authenticated local terminal connections."""

from __future__ import annotations

from typing import Self

from punt_lux.protocol.pty.control import (
    WIRE_VERSION,
    AttachRequest,
    HelloRequest,
    ListRequest,
    Request,
)
from punt_lux.ptyd import snapshot as _snapshots
from punt_lux.ptyd.core import SessionCore
from punt_lux.ptyd.peer import Peer
from punt_lux.ptyd.stream_output import StreamPublisher
from punt_lux.ptyd.viewers import ViewerBindings


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
        else:
            self._bindings.close_session(request.session, "session killed")
            self._core.kill(request.session)
            StreamPublisher.success(peer, request.request_id, {})

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
            snapshot = session.capture()
        except _snapshots.SnapshotError:
            peer.close()  # retry negotiation after parser ground; keep program alive
            return
        binding = self._bindings.add(peer, request.session, request.cols, request.rows)
        StreamPublisher.attach(
            binding, request.request_id, snapshot, session.describe()
        )
