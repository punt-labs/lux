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
from pathlib import Path
from typing import Self

from punt_lux.protocol import ReadyMessage, recv_message

logger = logging.getLogger(__name__)

# Seconds to wait for the handshake probe and for a spawned display to answer.
_PROBE_TIMEOUT = 1.0


# ---------------------------------------------------------------------------
# DisplayPaths — OO API for socket/pid/log path resolution and lifecycle
# ---------------------------------------------------------------------------


class DisplayPaths:
    """Resolve socket/PID/log paths and own the display process lifecycle.

    Liveness is authoritative: it is determined by connecting to the
    socket and confirming a ``ReadyMessage`` handshake, never by trusting
    a PID file (a recycled PID would read as alive). The socket a live
    server answers on is never unlinked. The PID file next to the socket
    is the single source of truth for reaping the owning process.
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

    def is_running(self) -> bool:
        """Return whether a live display answers the socket handshake.

        Connects to the socket and confirms a ``ReadyMessage`` arrives.
        A recycled PID cannot read as alive because the PID file is never
        consulted; a stale socket file with no listener reads as dead
        because the connection is refused.
        """
        if not self._socket_path.exists():
            return False
        probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        probe.settimeout(_PROBE_TIMEOUT)
        try:
            probe.connect(str(self._socket_path))
        except OSError:
            return False
        try:
            reply = recv_message(probe, timeout=_PROBE_TIMEOUT)
        except (OSError, ValueError):
            return False
        finally:
            probe.close()
        return isinstance(reply, ReadyMessage)

    # -- spawn --------------------------------------------------------------

    def ensure(self, timeout: float = 5.0) -> Path:
        """Ensure a display server is running, spawning one if needed.

        Idempotent: if a live display already answers the socket, reuse
        it and never spawn a second. Concurrent callers serialize on a
        file lock so only one spawns; the losers observe the winner's
        server on the re-check and reuse it. Returns the socket path.

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
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()

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
        """Block until the spawned display answers, or raise on timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.is_running():
                return self._socket_path
            time.sleep(0.1)
        msg = f"Display server failed to start within {timeout}s at {self._socket_path}"
        raise RuntimeError(msg)

    # -- cleanup / reap -----------------------------------------------------

    def cleanup_stale(self) -> None:
        """Remove the socket and PID file only when no server answers.

        Never unlinks a socket a live display is serving — liveness is
        confirmed by :meth:`is_running`'s handshake probe first.
        """
        if self.is_running():
            return
        self._clear_dead_files()

    def reap(self, timeout: float = 5.0) -> None:
        """Terminate the display owning this socket and clear its files.

        Signals the recorded PID only when a live display answers the
        socket, so a stale PID file whose PID was recycled is never
        signalled. A live socket is never unlinked: if the owner cannot
        be identified or refuses to exit, the files are left intact
        rather than orphaning a running window.
        """
        if not self.is_running():
            self._clear_dead_files()
            return
        pid = self._read_pid()
        if pid is None:
            logger.warning(
                "display alive on %s but PID file absent — cannot reap",
                self._socket_path,
            )
            return
        self._terminate(pid, timeout)
        if self.is_running():
            logger.warning(
                "display PID %d ignored termination on %s",
                pid,
                self._socket_path,
            )
            return
        self._clear_dead_files()

    def _clear_dead_files(self) -> None:
        """Unlink the socket and PID file of a display confirmed not running."""
        if self._socket_path.exists() and self._socket_path.is_socket():
            self._socket_path.unlink(missing_ok=True)
        self.remove_pid()

    def _read_pid(self) -> int | None:
        """Return the recorded display PID, or ``None`` when unreadable.

        ``None`` is the documented contract for absence — a missing or
        corrupt PID file — not a failed value production (PY-EH-8): the
        caller decides whether an unknown owner is signallable.
        """
        try:
            return int(self.pid_path.read_text().strip())
        except (ValueError, OSError):
            return None

    def _terminate(self, pid: int, timeout: float) -> None:
        """Send SIGTERM, escalating to SIGKILL if the process outlives *timeout*."""
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return  # already gone
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except OSError:
                return  # exited
            time.sleep(0.1)
        with contextlib.suppress(OSError):
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
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
