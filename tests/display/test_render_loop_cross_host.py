"""RenderLoop cross-host wiring -- the per-frame accept cadence (DES-090 W10).

Proves the render loop drives an injected CrossHostListener with the exact
discipline the design and W12's model require: ``accept_pending()`` at most
once per frame, every verified socket promoted onto the ordinary client set
(where the content gate then holds it to verify -> identify -> content), and
fail-closed when no listener is configured.
"""

from __future__ import annotations

import socket
import tempfile
from pathlib import Path
from typing import Self, final

from punt_lux.display import RenderLoop
from punt_lux.protocol import ReadyMessage, recv_message


def _sock_path() -> str:
    return str(Path(tempfile.mkdtemp(prefix="lux-")) / "xh.sock")


@final
class _FakeCrossHost:
    """Records ``accept_pending`` calls and hands back a preloaded ready list once."""

    _ready: list[socket.socket]
    accept_calls: int
    shutdown_calls: int

    def __new__(cls, ready: list[socket.socket]) -> Self:
        self = super().__new__(cls)
        self._ready = ready
        self.accept_calls = 0
        self.shutdown_calls = 0
        return self

    def accept_pending(self) -> None:
        self.accept_calls += 1

    def pump_ready(self) -> list[socket.socket]:
        out, self._ready = self._ready, []
        return out

    def shutdown(self) -> None:
        self.shutdown_calls += 1


class TestCrossHostPump:
    def test_accept_pending_is_called_exactly_once_per_pump(self) -> None:
        fake = _FakeCrossHost([])
        loop = RenderLoop(_sock_path(), cross_host_listener=fake)
        loop._pump_cross_host()
        assert fake.accept_calls == 1

    def test_a_verified_socket_is_promoted_and_greeted_but_unidentified(self) -> None:
        left, right = socket.socketpair()
        fake = _FakeCrossHost([left])
        loop = RenderLoop(_sock_path(), cross_host_listener=fake)
        try:
            loop._pump_cross_host()
            assert left in loop.socket_listener.clients
            # promoted exactly as an AF_UNIX peer: greeted with ReadyMessage...
            assert isinstance(recv_message(right, timeout=2.0), ReadyMessage)
            # ...but NOT identified -- the content gate turns away any scene
            # until its own ConnectMessage arrives (Invariant 1).
            assert loop.socket_listener.kind_of(left.fileno()) is None
        finally:
            left.close()
            right.close()

    def test_fail_closed_when_no_listener_is_configured(self) -> None:
        loop = RenderLoop(_sock_path())  # cross_host_listener defaults to None
        loop._pump_cross_host()  # must not raise
        assert loop.socket_listener.client_count == 0
