"""PeerBook frees a peer's viewer bindings when its connection closes."""

from __future__ import annotations

import select
import socket
import tempfile
from pathlib import Path
from typing import Self, cast

import pytest

from punt_lux.pty.dispatch import SessionDispatch
from punt_lux.pty.peer import Peer
from punt_lux.pty.peer_book import PeerBook
from punt_lux.pty.viewers import ViewerBindings
from punt_lux.wire.stream.frames import Frame, FrameKind

pytestmark = pytest.mark.integration


class _BindingDispatch:
    """Binds a viewer for the first peer it hears from and drops it on detach.


    The binding is made with the exact Peer the PeerBook delivers, so the
    test observes the daemon's real identity match, not a stand-in.
    """

    _bindings: ViewerBindings

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._bindings = ViewerBindings()
        return self

    @property
    def bindings(self) -> ViewerBindings:
        return self._bindings

    def receive(self, peer: Peer, frame: Frame) -> None:
        if not self._bindings.session("work"):
            self._bindings.add(peer, "work", 80, 24)

    def detach(self, peer: Peer) -> None:
        self._bindings.detach(peer)


def _listener() -> socket.socket:
    path = Path(tempfile.mkdtemp(prefix="lux-")) / "pty.sock"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.bind(str(path))
    server.listen(1)
    server.setblocking(False)
    return server


def test_a_closed_connection_drops_its_viewer_binding() -> None:
    """The Display closes its idle connection instead of sending CLOSE."""
    dispatch = _BindingDispatch()
    book = PeerBook(cast("SessionDispatch", dispatch), None)
    server = _listener()
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(server.getsockname())
    select.select([server], [], [], 1.0)
    book.accept(server)
    client.sendall(Frame(1, FrameKind.DATA, b"x").encode())  # binds the viewer
    for _ in range(50):
        readable, _, _ = select.select(list(book.readers), [], [], 0.05)
        book.service(readable, [])
        if dispatch.bindings.session("work"):
            break
    assert dispatch.bindings.session("work")

    client.close()
    for _ in range(50):
        readable, _, _ = select.select(list(book.readers), [], [], 0.05)
        book.service(readable, [])
        if not book.readers:
            break

    assert dispatch.bindings.session("work") == ()
    assert book.readers == ()
    server.close()
