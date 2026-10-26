"""A scripted display for tests of the Hub's link: a dialer and its peer ends.

Each dial makes a socket pair; the Hub link gets one end and the test drives the
other (:class:`Peer`), reading what the Hub wrote and answering as a display would.
"""

from __future__ import annotations

import contextlib
import socket
import threading
import time
from typing import TYPE_CHECKING, Self, final

from punt_lux.domain.hub.handshake_outcome import HandshakeResult
from punt_lux.protocol import (
    AckMessage,
    FrameReader,
    PingMessage,
    PongMessage,
    ReadyMessage,
    SceneMessage,
    encode_message,
)
from punt_lux.protocol.messages.wire_vocabulary import CLIENT_VOCABULARY

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from punt_lux.protocol import Message

__all__ = ["Call", "Display", "FlakySocket", "Peer", "Responder", "until"]


def until(condition: Callable[[], bool], timeout: float = 3.0) -> bool:
    """Poll ``condition`` until it holds or ``timeout`` passes."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.005)
    return condition()


@final
class Peer:
    """The display's end of one dialed connection."""

    _sock: socket.socket
    _reader: FrameReader
    _pending: list[Message]
    __slots__ = ("_pending", "_reader", "_sock")

    def __new__(cls, sock: socket.socket) -> Self:
        self = super().__new__(cls)
        self._sock = sock
        self._reader = FrameReader()
        self._pending = []
        return self

    def read(self, count: int = 1, timeout: float = 3.0) -> list[Message]:
        """Read ``count`` messages the Hub wrote, in order; fewer if time runs out."""
        deadline = time.monotonic() + timeout
        while len(self._pending) < count:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            self._sock.settimeout(remaining)
            try:
                chunk = self._sock.recv(65536)
            except TimeoutError:
                break
            if not chunk:
                break
            self._reader.feed(chunk)
            self._pending.extend(self._reader.drain_typed(CLIENT_VOCABULARY))
        taken, self._pending = self._pending[:count], self._pending[count:]
        return taken

    def send(self, *messages: Message) -> None:
        """Write replies, as the display would."""
        for message in messages:
            self._sock.sendall(encode_message(message))

    def send_raw(self, data: bytes) -> None:
        """Write bytes as they are."""
        self._sock.sendall(data)

    def close(self) -> None:
        """Hang up, as a display that went away."""
        self._sock.close()


@final
class FlakySocket:
    """A socket that fails or times out its next ``sendall`` when told to."""

    _sock: socket.socket
    _active: int
    _guard: threading.Lock
    fail_next_send: bool
    time_out_next_send: bool
    overlaps: int
    reader_overlaps: int
    _reading: int

    def __new__(cls, sock: socket.socket) -> Self:
        self = super().__new__(cls)
        self._sock = sock
        self._active = 0
        self._guard = threading.Lock()
        self.fail_next_send = False
        self.time_out_next_send = False
        self.overlaps = 0
        self.reader_overlaps = 0
        self._reading = 0
        return self

    def sendall(self, data: bytes) -> None:
        """Raise once, if told to, before writing anything."""
        if self.time_out_next_send:
            self.time_out_next_send = False
            msg = "the send timed out"
            raise BlockingIOError(msg)
        if self.fail_next_send:
            self.fail_next_send = False
            msg = "the socket fell over"
            raise OSError(msg)
        with self._exclusive():
            self._sock.sendall(data)

    def has_send_timeout(self) -> bool:
        """Whether ``SO_SNDTIMEO`` is set on the real socket."""
        packed = self._sock.getsockopt(socket.SOL_SOCKET, socket.SO_SNDTIMEO, 16)
        return packed != bytes(len(packed))

    def recv(self, size: int) -> bytes:
        """Read, counting a read that overlaps a write (a TLS socket forbids it)."""
        with self._guard:
            self._reading += 1
            if self._reading > 1:
                self.reader_overlaps += 1
        try:
            with self._exclusive():
                return self._sock.recv(size)
        finally:
            with self._guard:
                self._reading -= 1

    @contextlib.contextmanager
    def _exclusive(self) -> Generator[None]:
        with self._guard:
            self._active += 1
            if self._active > 1:
                self.overlaps += 1
        try:
            time.sleep(0.005)  # widen the window an unserialized caller would hit
            yield
        finally:
            with self._guard:
                self._active -= 1

    def __getattr__(self, name: str) -> object:
        return getattr(self._sock, name)


@final
class Display:
    """A dialer over socket pairs: ``peers[i]`` is the display end of dial ``i``."""

    peers: list[Peer]
    sockets: list[FlakySocket]
    dials: int

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self.peers = []
        self.sockets = []
        self.dials = 0
        return self

    def dial(self, connect_timeout: float) -> HandshakeResult:
        """Hand the Hub one end of a new pair."""
        ours, theirs = socket.socketpair()
        self.dials += 1
        flaky = FlakySocket(ours)
        self.sockets.append(flaky)
        self.peers.append(Peer(theirs))
        return HandshakeResult(
            sock=flaky,  # type: ignore[arg-type]  # a socket for every use the link makes
            endpoint=f"pair-{self.dials}",
            ready=ReadyMessage(),
        )

    @property
    def peer(self) -> Peer:
        """The display end of the latest dial."""
        return self.peers[-1]

    def close(self) -> None:
        """Hang up every peer."""
        for peer in self.peers:
            try:
                peer.close()
            except OSError:
                continue


@final
class Call[T]:
    """A call running on its own thread; its result or its exception, afterwards."""

    _thread: threading.Thread
    _result: list[T]
    _error: list[BaseException]
    __slots__ = ("_error", "_result", "_thread")

    def __new__(cls, fn: Callable[[], T]) -> Self:
        self = super().__new__(cls)
        self._result = []
        self._error = []

        def run() -> None:
            try:
                self._result.append(fn())
            except BaseException as exc:  # noqa: BLE001 - handed to the test thread
                self._error.append(exc)

        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()
        return self

    @property
    def done(self) -> bool:
        """Whether the call has returned or raised."""
        return not self._thread.is_alive()

    def wait(self, timeout: float = 3.0) -> bool:
        """Wait for the call to end; whether it did."""
        self._thread.join(timeout)
        return self.done

    @property
    def result(self) -> T:
        """What the call returned; fails the test if it raised or has not ended."""
        assert self.done, "the call has not ended"
        assert not self._error, f"the call raised {self._error[0]!r}"
        return self._result[0]

    @property
    def error(self) -> BaseException | None:
        """What the call raised, or ``None``."""
        assert self.done, "the call has not ended"
        return self._error[0] if self._error else None


@final
class Responder:
    """A display that answers every dial as the real one does, and can be poisoned.

    A ping is answered with its pong. By default a scene is acked on receipt, and a
    scene named in ``poison`` is read and never acked: the display hangs up on it, a
    frame after it read the scene.

    With ``at_swap`` the display is the real one: a scene is installed on receipt and
    its ack is held until the next completed swap, when every held ack goes out in
    receipt order. A held poison scene crashes the swap that would have sent it: the
    display hangs up with every held ack unsent. ``swap()`` is that swap, called by
    the test, or by the responder itself once it has been idle for ``swap_after``
    seconds (``auto_swap``), as frames complete on a live display. ``seen`` lists
    every scene the display read, in order.
    """

    _display: Display
    _poison: frozenset[str]
    _at_swap: bool
    _swap_after: float | None
    _stop: threading.Event
    _thread: threading.Thread
    _held: list[tuple[Peer, str]]
    _guard: threading.Lock
    seen: list[str]

    def __new__(
        cls,
        display: Display,
        poison: frozenset[str] = frozenset(),
        *,
        at_swap: bool = False,
        auto_swap: bool = True,
        swap_after: float = 0.03,
    ) -> Self:
        self = super().__new__(cls)
        self._display = display
        self._poison = poison
        self._at_swap = at_swap
        self._swap_after = swap_after if at_swap and auto_swap else None
        self._stop = threading.Event()
        self._held = []
        self._guard = threading.Lock()
        self.seen = []
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        """Stop answering; the dials stay as they are."""
        self._stop.set()
        self._thread.join(timeout=2.0)

    def swap(self) -> None:
        """Complete a swap: send every held ack in receipt order, or die painting."""
        with self._guard:
            held, self._held = self._held, []
        if any(scene in self._poison for _, scene in held):
            self._display.close()  # the crash is the swap that never completes
            return
        for peer, scene in held:
            with contextlib.suppress(OSError):
                peer.send(AckMessage(scene_id=scene))

    @property
    def held(self) -> list[str]:
        """The scenes installed and not yet acked, in receipt order."""
        with self._guard:
            return [scene for _, scene in self._held]

    def _serve(self) -> None:
        quiet_since = time.monotonic()
        while not self._stop.is_set():
            idle = True
            for peer in list(self._display.peers):
                try:
                    messages = peer.read(1, timeout=0.002)
                except OSError:
                    continue  # a peer this display already hung up on
                for message in messages:
                    idle = False
                    self._answer(peer, message)
            if not idle:
                quiet_since = time.monotonic()
                continue
            if (
                self._swap_after is not None
                and self.held
                and time.monotonic() - quiet_since >= self._swap_after
            ):
                self.swap()
            time.sleep(0.002)

    def _answer(self, peer: Peer, message: Message) -> None:
        with contextlib.suppress(OSError):
            if isinstance(message, PingMessage):
                peer.send(PongMessage(ts=message.ts))
            elif isinstance(message, SceneMessage):
                self.seen.append(message.id)
                if self._at_swap:
                    with self._guard:
                        self._held.append((peer, message.id))
                elif message.id in self._poison:
                    peer.close()
                else:
                    peer.send(AckMessage(scene_id=message.id))
