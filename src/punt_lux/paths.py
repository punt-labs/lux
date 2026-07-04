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

# Seconds to confirm a process has exited after SIGKILL (asynchronous delivery).
_SIGKILL_GRACE = 2.0

# Peer-credential socket options by platform: (level, optname, buflen).
# macOS LOCAL_PEERPID (SOL_LOCAL=0) and Linux SO_PEERCRED (SOL_SOCKET=1) both
# carry the owning PID in the first 4 bytes. Raw values sidestep the socket
# module's platform-guarded symbols, keeping the query reachable everywhere.
_PEER_PID_OPT: dict[str, tuple[int, int, int]] = {
    "darwin": (0, 0x002, 4),
    "linux": (1, 17, 12),
}

# An undecodable reply from a connected peer still proves a live owner (ACCEPTING):
# non-object payloads raise AttributeError; over-deep JSON raises RecursionError.
_RECV_ERRS = (OSError, ValueError, KeyError, TypeError, AttributeError, RecursionError)


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

    The socket is authoritative for liveness and identity: a connection
    that is accepted proves a live owner (never spawned over nor unlinked),
    and the reap target is the socket's OS peer credential, not a PID file.
    """

    _socket_path: Path

    def __new__(cls, socket_path: Path | None = None) -> Self:
        self = super().__new__(cls)
        self._socket_path = socket_path or cls._default_path()
        return self

    @staticmethod
    def _default_path() -> Path:
        """Return the default socket path: ``$LUX_SOCKET``, else
        ``$XDG_RUNTIME_DIR/lux/`` or ``/tmp/lux-$USER/``, plus ``display.sock``."""
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
        """Return the socket's liveness: ``DEAD`` only on a definitive
        no-listener, else ``ACCEPTING`` (or ``READY`` on a clean handshake)."""
        if not self._socket_path.exists():
            return SocketLiveness.DEAD
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(_PROBE_TIMEOUT)
            try:
                probe.connect(str(self._socket_path))
            except (ConnectionRefusedError, FileNotFoundError):
                return SocketLiveness.DEAD  # no listener / file gone
            except OSError:
                return SocketLiveness.ACCEPTING  # timeout/EMFILE/ambiguous — not dead
            try:
                reply = recv_message(probe, timeout=_PROBE_TIMEOUT)
            except _RECV_ERRS:
                return SocketLiveness.ACCEPTING  # a live owner answered
            if isinstance(reply, ReadyMessage):
                return SocketLiveness.READY
            return SocketLiveness.ACCEPTING

    def is_running(self) -> bool:
        """Return whether a live process owns the socket (accepts a connection)."""
        return self._probe() is not SocketLiveness.DEAD

    # -- spawn --------------------------------------------------------------

    def ensure(self, timeout: float = 5.0) -> Path:
        """Ensure a live display, spawning one under a file lock if needed.

        Idempotent and concurrency-safe: an existing owner is reused, and
        racing callers serialize so only one spawns. Returns the socket
        path; raises ``RuntimeError`` on start timeout.
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
        """Unlink the socket and PID file only when no owner accepts —
        never orphan a live owner (deadness confirmed by :meth:`is_running`)."""
        if self.is_running():
            return
        self._clear_dead_files()

    def reap(self, timeout: float = 5.0) -> None:
        """Terminate the socket's owner and clear its files; raise on failure.

        The owner is the socket's OS peer credential. A dead socket is
        cleared. An unresolved owner or one that outlives ``SIGKILL`` raises
        rather than orphaning a window a restart would stack a second over.
        """
        if not self.is_running():
            self._clear_dead_files()
            return
        pid = self._peer_pid()
        if pid is None:
            # TOCTOU: the owner may have exited between the probe and peer read.
            if not self.is_running():
                self._clear_dead_files()
                return
            msg = (
                f"display alive on {self._socket_path} but its owner could not "
                "be resolved via the socket peer credential — refusing to reap"
            )
            raise RuntimeError(msg)
        self._terminate(pid, timeout)  # raises if the owner outlives SIGKILL
        self._clear_dead_files()

    def _peer_pid(self) -> int | None:
        """Return the socket owner's PID from its OS peer credential, or ``None``.

        ``None`` is an unresolvable owner — unreadable peer, unsupported
        platform, or a non-positive PID the signal path must never os.kill.
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
            pid = int.from_bytes(cred[:4], sys.byteorder)
            return pid if pid > 0 else None

    def _clear_dead_files(self) -> None:
        """Unlink the socket and PID file of a display confirmed dead."""
        if self._socket_path.exists() and self._socket_path.is_socket():
            # WARNING so the destructive unlink surfaces even from the reap
            # `python -c`, which configures no handler (lastResort is WARNING).
            logger.warning("removing dead display socket %s", self._socket_path)
            self._socket_path.unlink(missing_ok=True)
        self.remove_pid()

    def _terminate(self, pid: int, timeout: float) -> None:
        """Terminate *pid* (SIGTERM→SIGKILL), confirming death; raise if it survives.

        Death is confirmed by polling ``os.kill(pid, 0)`` — SIGKILL is async,
        so the caller trusts this over the lingering socket. ``PermissionError``
        propagates; ``os.kill`` retries EINTR itself (PEP 475).
        """
        if pid <= 0:  # never signal a process group; the caller must resolve one
            msg = f"refusing to signal non-positive PID {pid}"
            raise ValueError(msg)
        for sig, grace in ((signal.SIGTERM, timeout), (signal.SIGKILL, _SIGKILL_GRACE)):
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                return  # exited
            if self._await_exit(pid, grace):
                return
        msg = f"PID {pid} survived SIGKILL"
        raise RuntimeError(msg)

    def _await_exit(self, pid: int, timeout: float) -> bool:
        """Return ``True`` once *pid* has exited (by PID slot or released socket)."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with contextlib.suppress(ChildProcessError):
                os.waitpid(pid, os.WNOHANG)  # reap a child zombie; ignore non-children
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
            if not self.is_running():  # zombie released the socket — owner gone
                return True
            time.sleep(0.05)
        return False

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
