"""Line-delimited JSON over Unix sockets. Minimal.

Per io-model.md: IPC carries Updates and Events. The Connection
abstraction is the bytes-on-the-wire layer; Decoder/Encoder sit on
top of it.
"""

from __future__ import annotations

import json
import socket
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path


type WireDict = dict[str, object]


class LineSocket:
    """One full-duplex line-delimited JSON conversation over a Unix socket.

    Owned by whichever process accept()ed or connect()ed the socket.
    Thread-safe send. Reading is single-threaded (one reader thread per
    LineSocket in the spike's tier processes)."""

    _sock: socket.socket
    _send_lock: threading.Lock
    _recv_buf: bytes

    def __new__(cls, sock: socket.socket) -> "LineSocket":
        self = object.__new__(cls)
        self._sock = sock
        self._send_lock = threading.Lock()
        self._recv_buf = b""
        return self

    def send_line(self, payload: WireDict) -> None:
        line = (json.dumps(payload) + "\n").encode("utf-8")
        with self._send_lock:
            self._sock.sendall(line)

    def iter_lines(self) -> Iterator[WireDict]:
        """Blocking generator. Yields decoded JSON dicts until the
        peer closes the socket."""
        while True:
            while b"\n" not in self._recv_buf:
                chunk = self._sock.recv(4096)
                if not chunk:
                    return
                self._recv_buf += chunk
            line, _, rest = self._recv_buf.partition(b"\n")
            self._recv_buf = rest
            if not line:
                continue
            yield json.loads(line.decode("utf-8"))

    def close(self) -> None:
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._sock.close()


@contextmanager
def listen_unix(path: str | Path) -> Iterator[socket.socket]:
    """Server side: bind + listen on a Unix socket path. Cleans up the
    path on exit. Yields the listening socket."""
    p = Path(path)
    if p.exists():
        p.unlink()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(str(p))
        sock.listen(8)
        yield sock
    finally:
        sock.close()
        if p.exists():
            p.unlink()


def connect_unix(path: str | Path, retries: int = 50, delay: float = 0.05) -> LineSocket:
    """Client side: connect with brief retry to allow the listening
    process to come up."""
    import time

    last_err: Exception | None = None
    for _ in range(retries):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            sock.connect(str(path))
            return LineSocket(sock)
        except (FileNotFoundError, ConnectionRefusedError) as err:
            sock.close()
            last_err = err
            time.sleep(delay)
    raise RuntimeError(f"could not connect to {path}: {last_err}")


def spawn_reader(line_socket: LineSocket, handler: Callable[[WireDict], None]) -> threading.Thread:
    """Run a daemon thread that reads lines and dispatches to handler."""

    def loop() -> None:
        for payload in line_socket.iter_lines():
            try:
                handler(payload)
            except Exception as exc:
                import sys
                print(f"[reader] handler error: {exc!r}", file=sys.stderr, flush=True)

    t = threading.Thread(target=loop, name="line-socket-reader", daemon=True)
    t.start()
    return t
