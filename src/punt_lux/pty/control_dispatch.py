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
)

if TYPE_CHECKING:
    from punt_lux.pty.core import SessionCore
    from punt_lux.pty.peer import Peer
    from punt_lux.pty.viewers import ViewerBindings


class ControlDispatch:
    """Negotiate, create, resume, inspect and explicitly terminate sessions."""

    _core: SessionCore
    _bindings: ViewerBindings
    _admission: PeerAdmission
    _attach: SessionAttach

    def __new__(cls, core: SessionCore, bindings: ViewerBindings) -> Self:
        self = super().__new__(cls)
        self._core, self._bindings = core, bindings
        self._admission = PeerAdmission.current()
        self._attach = SessionAttach(core, bindings)
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
            self._attach.execute(peer, request)
        elif isinstance(request, ListRequest):
            listing = self._core.describe()
            StreamPublisher.success(peer, request.request_id, {"sessions": listing})
        elif isinstance(request, KillRequest):
            self._bindings.close_session(request.session, "session killed")
            self._core.kill(request.session)
            StreamPublisher.success(peer, request.request_id, {})
        elif isinstance(request, NewRequest):
            session = self._core.create(request)
            StreamPublisher.success(peer, request.request_id, session.describe())
        else:
            # watch decodes on the wire but the daemon does not act on it yet;
            # refuse it rather than run it as something else.
            StreamPublisher.failure(
                peer, request.request_id, f"unsupported operation {request.OP}"
            )
