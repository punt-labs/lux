"""Line-delimited JSON over Unix sockets — io-model transport.

Per docs/oo-refactor/pr3-v2.1-design.md §5 and the spike at
``spikes/io_model_v1/src/lux_spike/connection.py``: ``LineSocket`` is
the bytes-on-the-wire layer; ``Decoder``/``Encoder`` sit on top. One
``LineSocket`` owns one full-duplex conversation. Reads are
single-threaded (one reader per socket); sends are serialized via an
internal lock so multiple producers can share one connection. The
in-memory paired-queue variant lives in ``in_memory_connection.py``
(PY-OO-2: one concept per module); both expose the same ``send_line``
/ ``iter_lines`` / ``close`` shape so consumers don't branch on backend.
D7 (design §6): consumed by tests only; ``DisplayClient`` keeps its
existing length-prefixed wire path until a coordinated cross-tier flip.
"""

from __future__ import annotations

import json
import logging
import socket
import threading
import time
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from collections.abc import Callable, Generator, Iterator

__all__ = ["LineSocket", "WireDict", "connect_unix", "listen_unix", "spawn_reader"]

logger = logging.getLogger(__name__)

type WireDict = dict[str, object]

_RECV_CHUNK = 4096
_DEFAULT_RETRIES = 50
_DEFAULT_RETRY_DELAY = 0.05
_LISTEN_BACKLOG = 8


class LineSocket:
    """One full-duplex line-delimited JSON conversation over a Unix socket.

    Owned by whichever process accepted or connected the socket.
    Thread-safe send; reading is single-threaded (one reader thread per
    ``LineSocket`` in the io-model tier processes).
    """

    _sock: socket.socket
    _send_lock: threading.Lock
    _recv_buf: bytes

    def __new__(cls, sock: socket.socket) -> Self:
        self = super().__new__(cls)
        self._sock = sock
        self._send_lock = threading.Lock()
        self._recv_buf = b""
        return self

    def send_line(self, payload: WireDict) -> None:
        """Serialize ``payload`` as one JSON line and send it."""
        line = (json.dumps(payload) + "\n").encode("utf-8")
        with self._send_lock:
            self._sock.sendall(line)

    def iter_lines(self) -> Iterator[WireDict]:
        """Yield decoded JSON dicts until the peer closes the socket."""
        while True:
            while b"\n" not in self._recv_buf:
                chunk = self._sock.recv(_RECV_CHUNK)
                if not chunk:
                    return
                self._recv_buf += chunk
            line, _, self._recv_buf = self._recv_buf.partition(b"\n")
            if line:
                yield json.loads(line.decode("utf-8"))

    def close(self) -> None:
        """Shutdown and close the underlying socket."""
        with suppress(OSError):
            self._sock.shutdown(socket.SHUT_RDWR)
        self._sock.close()


@contextmanager
def listen_unix(path: str | Path) -> Generator[socket.socket]:
    """Bind + listen on a Unix socket path; clean up on exit."""
    p = Path(path)
    if p.exists():
        p.unlink()
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(str(p))
        sock.listen(_LISTEN_BACKLOG)
        yield sock
    finally:
        sock.close()
        if p.exists():
            p.unlink()


def connect_unix(
    path: str | Path,
    retries: int = _DEFAULT_RETRIES,
    delay: float = _DEFAULT_RETRY_DELAY,
) -> LineSocket:
    """Connect to a Unix socket with brief retry; close ``sock`` on any failure."""
    # Non-retry exceptions (PermissionError, generic OSError) propagate after
    # ``finally`` closes ``sock`` so the fd is never leaked; retry-eligible
    # races (FileNotFoundError, ConnectionRefusedError) sleep and loop.
    last_err: Exception | None = None
    for _ in range(retries):
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connected = False
        try:
            sock.connect(str(path))
        except (FileNotFoundError, ConnectionRefusedError) as err:
            last_err = err
            time.sleep(delay)
        else:
            connected = True
            return LineSocket(sock)
        finally:
            if not connected:
                sock.close()
    msg = f"could not connect to {path}: {last_err}"
    raise RuntimeError(msg)


def spawn_reader(
    line_socket: LineSocket, handler: Callable[[WireDict], None]
) -> threading.Thread:
    """Read lines on a daemon thread; own and close ``line_socket`` on exit.

    Ownership transfers to the thread — callers must not close. The
    ``finally`` guarantees close on peer EOF or any ``iter_lines``
    failure, preventing fd leaks; the outer ``except`` surfaces those
    failures so the thread doesn't die silently.
    """

    def loop() -> None:
        try:
            for payload in line_socket.iter_lines():
                try:
                    handler(payload)
                except Exception:
                    logger.exception("line-socket reader: handler raised")
        except Exception:
            logger.exception("line-socket reader: iter_lines terminated unexpectedly")
        finally:
            line_socket.close()

    t = threading.Thread(target=loop, name="line-socket-reader", daemon=True)
    t.start()
    return t
