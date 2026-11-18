"""Control operations over authenticated local terminal connections."""

from __future__ import annotations

from typing import Self

from punt_lux.protocol.pty.control import (
    WIRE_VERSION,
    AttachRequest,
    ControlCodec,
    HelloRequest,
    ListRequest,
)
from punt_lux.protocol.pty.frames import Frame, FrameKind
from punt_lux.protocol.pty.replies import FailureReply, ReplyCodec, SuccessReply
from punt_lux.ptyd.bindings import ViewerBindings
from punt_lux.ptyd.core import SessionCore
from punt_lux.ptyd.peer import Peer
from punt_lux.ptyd.snapshot import snapshot_version


class ControlDispatch:
    """Negotiate, create/attach, inspect and explicitly terminate sessions."""

    _core: SessionCore
    _bindings: ViewerBindings

    def __new__(cls, core: SessionCore, bindings: ViewerBindings) -> Self:
        self = super().__new__(cls)
        self._core, self._bindings = core, bindings
        return self

    def receive(self, peer: Peer, frame: Frame) -> None:
        if frame.kind is not FrameKind.DATA:
            raise ValueError("control channel accepts DATA only")
        request = ControlCodec.decode(frame.payload)
        try:
            if isinstance(request, HelloRequest):
                self._hello(peer, request)
                return
            if not peer.ready:
                raise ValueError("hello must precede session requests")
            if isinstance(request, AttachRequest):
                self._attach(peer, request)
            elif isinstance(request, ListRequest):
                self._success(
                    peer, request.request_id, {"sessions": self._core.describe()}
                )
            else:
                self._core.kill(request.session)
                self._bindings.close_session(request.session, "session killed")
                self._success(peer, request.request_id, {})
        except (ValueError, RuntimeError, OSError) as error:
            reply = FailureReply(request.request_id, str(error)[:4096])
            peer.queue(Frame(0, FrameKind.DATA, ReplyCodec.encode(reply)))

    def _hello(self, peer: Peer, request: HelloRequest) -> None:
        if (
            request.version != WIRE_VERSION
            or request.snapshot_version != snapshot_version()
        ):
            raise ValueError(
                "protocol or snapshot version mismatch; restart client/daemon together"
            )
        peer.mark_ready()
        self._success(
            peer,
            request.request_id,
            {"version": WIRE_VERSION, "snapshot_version": snapshot_version()},
        )

    def _attach(self, peer: Peer, request: AttachRequest) -> None:
        if self._bindings.session(request.session) is not None:
            raise ValueError("session already has an attached viewer")
        session = self._core.acquire(request)
        self._core.resize(request.session, request.cols, request.rows)
        snapshot = session.capture()
        binding = self._bindings.add(peer, request.session)
        metadata = snapshot.to_dict()
        metadata["channel"] = binding.channel
        self._success(peer, request.request_id, metadata)
        for offset in range(0, len(snapshot.data), 64 * 1024):
            peer.queue(
                Frame(
                    binding.channel,
                    FrameKind.SNAPSHOT,
                    snapshot.data[offset : offset + 64 * 1024],
                )
            )

    @staticmethod
    def _success(peer: Peer, request_id: int, result: dict[str, object]) -> None:
        reply = SuccessReply(request_id, result)
        peer.queue(Frame(0, FrameKind.DATA, ReplyCodec.encode(reply)))
