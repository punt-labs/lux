"""Control operations over authenticated local terminal connections."""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from punt_lux.pty.peer_admission import PeerAdmission
from punt_lux.pty.session_attach import SessionAttach
from punt_lux.pty.stream_output import StreamPublisher
from punt_lux.wire.stream.control import (
    AttachRequest,
    HelloRequest,
    KillRequest,
    ListRequest,
    NewRequest,
    Request,
    WatchRequest,
)

if TYPE_CHECKING:
    from punt_lux.pty.peer import Peer
    from punt_lux.pty.session_roster import SessionRoster


class ControlDispatch:
    """Negotiate, create, resume, inspect and explicitly terminate sessions."""

    _roster: SessionRoster
    _admission: PeerAdmission
    _attach: SessionAttach

    def __new__(cls, roster: SessionRoster, attach: SessionAttach) -> Self:
        self = super().__new__(cls)
        self._roster, self._attach = roster, attach
        self._admission = PeerAdmission.current()
        return self

    def execute(self, peer: Peer, request: Request) -> None:
        if isinstance(request, HelloRequest):
            result = self._admission.admit(peer, request)
            StreamPublisher.success(peer, request.request_id, result)
        else:
            self._operate(peer, request)

    def _operate(self, peer: Peer, request: Request) -> None:
        self._admission.require_ready(peer)
        if isinstance(request, AttachRequest):
            self._roster.require_not_watching(peer)
            self._attach.execute(peer, request)
        elif isinstance(request, ListRequest):
            listing = self._roster.describe()
            StreamPublisher.success(peer, request.request_id, {"sessions": listing})
        elif isinstance(request, NewRequest):
            session = self._roster.create(request)
            StreamPublisher.success(peer, request.request_id, session.describe())
        elif isinstance(request, WatchRequest):
            self._roster.watch(peer)
            StreamPublisher.success(peer, request.request_id, {})
        elif isinstance(request, KillRequest):
            self._roster.kill(request.session)
            StreamPublisher.success(peer, request.request_id, {})
        else:
            raise ValueError(f"unsupported operation {request.OP}")
