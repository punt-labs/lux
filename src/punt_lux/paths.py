"""Socket path discovery and display process lifecycle helpers.

Shared between the display server and client — no ImGui dependency.
"""

from __future__ import annotations

import contextlib
import fcntl
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Generator
from enum import Enum, auto
from pathlib import Path
from typing import Self

from punt_lux.protocol import ReadyMessage, recv_message

logger = logging.getLogger(__name__)

# Seconds to wait for the handshake probe and for a spawned display to answer.
_PROBE_TIMEOUT = 1.0

# Peer-credential socket options by platform: (level, optname, buflen).
# macOS LOCAL_PEERPID (SOL_LOCAL=0) and Linux SO_PEERCRED (SOL_SOCKET=1) both
# carry the owning PID in the first 4 bytes. Raw values sidestep the socket
# module's platform-guarded symbols, keeping the query reachable everywhere.
_PEER_PID_OPT: dict[str, tuple[int, int, int]] = {
    "darwin": (0, 0x002, 4),
    "linux": (1, 17, 12),
}


class SocketLiveness(Enum):
    """Observed socket state: dead (no owner), accepting, or handshake-ready."""

    DEAD = auto()
    ACCEPTING = auto()
    READY = auto()


# ---------------------------------------------------------------------------
# DisplayPaths — OO API for socket/pid/log path resolution and lifecycle
# ---------------------------------------------------------------------------


class DisplayPaths:
    """Resolve socket/PID/log paths and own the display process lifecycle.

    The socket is authoritative for both liveness and identity. A
    connection that is accepted proves a live owner — even when the
    handshake is slow (mid-render, breakpoint, slow GPU) — so a socket
    that accepts is never spawned over nor unlinked. Identity (which
    process to reap) is the socket's OS peer credential, never a
    recyclable or corruptible PID file.
    """

    _socket_path: Path

    def __new__(cls, socket_path: Path | None = None) -> Self:
        self = super().__new__(cls)
        self._socket_path = socket_path or cls._default_path()
        return self

    @staticmethod
    def _default_path() -> Path:
        """Return the default Unix domain socket path for the display server.

        Resolution order:
        1. ``$LUX_SOCKET`` environment variable
        2. ``$XDG_RUNTIME_DIR/lux/display.sock``
        3. ``/tmp/lux-$USER/display.sock``
        """
        env = os.environ.get("LUX_SOCKET")
        if env:
            return Path(env)

        xdg = os.environ.get("XDG_RUNTIME_DIR")
        if xdg:
            return Path(xdg) / "lux" / "display.sock"

        user = os.environ.get("USER", "unknown")
        return Path(f"/tmp/lux-{user}/display.sock")  # noqa: S108

    @property
    def socket_path(self) -> Path:
        """Return the socket path."""
        return self._socket_path

    @property
    def pid_path(self) -> Path:
        """Return the PID file path for this socket."""
        return self._socket_path.with_suffix(".sock.pid")

    @property
    def log_path(self) -> Path:
        """Return the log file path for this socket."""
        return self._socket_path.with_suffix(".sock.log")

    @property
    def _lock_path(self) -> Path:
        """Return the spawn-lock file path for this socket."""
        return self._socket_path.with_suffix(".sock.lock")

    # -- liveness -----------------------------------------------------------

    def _probe(self) -> SocketLiveness:
        """Return the socket's liveness by connecting and reading a reply.

        ``DEAD`` when the file is absent or the connection is refused —
        no owner. ``ACCEPTING`` when a process accepts the connection but
        the handshake is absent or slower than ``_PROBE_TIMEOUT``.
        ``READY`` when a ``ReadyMessage`` completes.
        """
        if not self._socket_path.exists():
            return SocketLiveness.DEAD
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(_PROBE_TIMEOUT)
            try:
                probe.connect(str(self._socket_path))
            except OSError:
                return SocketLiveness.DEAD
            try:
                reply = recv_message(probe, timeout=_PROBE_TIMEOUT)
            except (OSError, ValueError):
                return SocketLiveness.ACCEPTING
            if isinstance(reply, ReadyMessage):
                return SocketLiveness.READY
            return SocketLiveness.ACCEPTING

    def is_running(self) -> bool:
        """Return whether a live process owns the socket (accepts a connection)."""
        return self._probe() is not SocketLiveness.DEAD

    # -- spawn --------------------------------------------------------------

    def ensure(self, timeout: float = 5.0) -> Path:
        """Ensure a display server is running, spawning one if needed.

        Idempotent: if a live display already owns the socket, reuse it
        and never spawn a second. Concurrent callers serialize on a file
        lock so only one spawns; the losers observe the winner's server
        on the re-check and reuse it. Returns the socket path.

        Raises ``RuntimeError`` if the display fails to start within
        *timeout*.
        """
        if self.is_running():
            return self._socket_path
        with self._spawn_lock():
            # Double-checked under the lock — a racing caller may have
            # spawned the display while we waited to acquire it.
            if self.is_running():
                return self._socket_path
            self.cleanup_stale()
            self._spawn()
            return self._await_ready(timeout)

    @contextlib.contextmanager
    def _spawn_lock(self) -> Generator[None]:
        """Serialize spawns across processes and threads via a file lock."""
        self._socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        lock_file = self._lock_path.open("w")
        try:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            lock_file.close()  # closing the fd releases the advisory lock

    def _spawn(self) -> None:
        """Launch the display server subprocess, detached from this session."""
        self._socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._socket_path.parent.chmod(0o700)
        log_file = self.log_path.open("w")
        cmd = [
            sys.executable,
            "-m",
            "punt_lux",
            "display",
            "--socket",
            str(self._socket_path),
        ]
        try:
            subprocess.Popen(  # noqa: S603
                cmd,
                start_new_session=True,
                stdout=log_file,
                stderr=log_file,
            )
        finally:
            log_file.close()

    def _await_ready(self, timeout: float) -> Path:
        """Block until the spawned display completes its handshake, or raise."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._probe() is SocketLiveness.READY:
                return self._socket_path
            time.sleep(0.1)
        msg = f"Display server failed to start within {timeout}s at {self._socket_path}"
        raise RuntimeError(msg)

    # -- cleanup / reap -----------------------------------------------------

    def cleanup_stale(self) -> None:
        """Remove the socket and PID file only when no process owns the socket.

        A socket that still accepts a connection is never unlinked — that
        would orphan a live owner. Deadness is confirmed by
        :meth:`is_running` first.
        """
        if self.is_running():
            return
        self._clear_dead_files()

    def reap(self, timeout: float = 5.0) -> None:
        """Terminate the display owning this socket; raise if it survives.

        Identity is the socket's OS peer credential, never a PID file. A
        dead socket's files are cleared. A live socket is never unlinked
        until its owner exits; an owner that cannot be resolved or that
        outlives ``SIGKILL`` raises ``RuntimeError`` rather than leaving
        an orphan a restart would spawn a second window over.
        """
        if not self.is_running():
            self._clear_dead_files()
            return
        pid = self._peer_pid()
        if pid is None:
            msg = (
                f"display alive on {self._socket_path} but its owner could not "
                "be resolved via the socket peer credential — refusing to reap"
            )
            raise RuntimeError(msg)
        self._terminate(pid, timeout)
        if self.is_running():
            msg = f"display PID {pid} on {self._socket_path} survived termination"
            raise RuntimeError(msg)
        self._clear_dead_files()

    def _peer_pid(self) -> int | None:
        """Return the PID bound to the socket via its OS peer credential.

        Reads ``LOCAL_PEERPID`` (macOS) or ``SO_PEERCRED`` (Linux) — the
        true owner independent of the PID file. ``None`` signals an
        unreadable peer (connection refused or an unsupported platform);
        on a live socket that is a caller-visible failure, not a fallback.
        """
        opt = _PEER_PID_OPT.get(sys.platform)
        if opt is None:
            return None
        level, optname, size = opt
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(_PROBE_TIMEOUT)
            try:
                probe.connect(str(self._socket_path))
                cred = probe.getsockopt(level, optname, size)
            except OSError:
                return None
            return int.from_bytes(cred[:4], sys.byteorder)

    def _clear_dead_files(self) -> None:
        """Unlink the socket and PID file of a display confirmed dead."""
        if self._socket_path.exists() and self._socket_path.is_socket():
            logger.info("removing dead display socket %s", self._socket_path)
            self._socket_path.unlink(missing_ok=True)
        self.remove_pid()

    def _terminate(self, pid: int, timeout: float) -> None:
        """Send SIGTERM, escalating to SIGKILL if the process outlives *timeout*.

        A vanished process (``ProcessLookupError``) is success. A
        ``PermissionError`` propagates — the process is alive but cannot
        be signalled, which the caller surfaces rather than swallows.
        ``os.kill`` retries interrupted syscalls itself (PEP 475).
        """
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return  # already gone
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return  # exited
            time.sleep(0.1)
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGKILL)

    # -- PID file -----------------------------------------------------------

    def write_pid(self) -> None:
        """Write the current process PID next to the socket file."""
        self.pid_path.write_text(str(os.getpid()))

    def remove_pid(self) -> None:
        """Remove the PID file for the socket path."""
        self.pid_path.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Hub path helpers — module-level functions for luxd (not display-server)
# ---------------------------------------------------------------------------


def hub_dir() -> Path:
    """Return the hub state directory: ~/.punt-labs/lux/"""
    return Path.home() / ".punt-labs" / "lux"


def hub_pid_path() -> Path:
    """Return the PID file path for luxd."""
    return hub_dir() / "hub.pid"


def hub_port_path() -> Path:
    """Return the port file path for luxd."""
    return hub_dir() / "hub.port"


def hub_log_dir() -> Path:
    """Return the log directory for luxd."""
    return hub_dir() / "logs"


def read_hub_port() -> int | None:
    """Read the hub port from the port file. Returns None if not available."""
    path = hub_port_path()
    if not path.exists():
        return None
    try:
        return int(path.read_text().strip())
    except (ValueError, OSError) as exc:
        logger.warning("Could not read hub port from %s: %s", path, exc)
        return None


def is_hub_running() -> bool:
    """Check whether luxd is running by reading its PID file."""
    pid_path = hub_pid_path()
    if not pid_path.exists():
        return False
    try:
        pid = int(pid_path.read_text().strip())
    except (ValueError, OSError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
