"""Behavioral tests for the PID resolution in plugin/hooks/session-start.sh.

Claude Code invokes SessionStart hooks through a short-lived ``sh`` wrapper: the
hook's own ``$PPID`` names that wrapper, not the long-running ``claude`` process
that actually owns the session. lux-beads was spawned watching ``$PPID``
directly, so its SessionWatch saw the wrapper vanish within seconds and left
before ever registering in the Lux menu (lux-zrnd).

These tests drive the real hook script as a subprocess at the bottom of a real
three-level process tree — a stand-in ``claude`` process, a wrapper that forks
it away, and the hook script itself — and assert it resolves the *grandparent*
pid, verified by command name, rather than the wrapper it was directly forked
from. A fixture ``lux-beads`` stub on ``PATH`` captures the ``--session-pid``
argument the script actually passed, so this is an outside-in check: nothing
here reads the script's internals, only what it does.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import time
from pathlib import Path
from typing import Self, final

import pytest

_SCRIPT = (
    Path(__file__).resolve().parent.parent / "plugin" / "hooks" / "session-start.sh"
)

_RELAY_SH = """#!/usr/bin/env bash
# Forks "$@" as a genuine child (backgrounding always forks) and waits for it,
# so each level in the tree is a distinct process with the expected parent.
if [[ -n "${RELAY_TRACE_FILE:-}" ]]; then
  echo "$$" >> "$RELAY_TRACE_FILE"
fi
"$@" &
wait
"""


@final
class ArgvCaptureStub:
    """A fake executable on ``PATH`` that records the argv it was run with.

    The hook backgrounds ``lux-beads`` with ``nohup ... & disown`` — pure
    fire-and-forget — so the hook script's own exit is no guarantee the stub
    has run yet. ``argv()`` polls for the capture file instead of narrowing
    the race with a blind ``sleep``.

    *write_delay* holds the stub between opening its output and writing the
    argv, widening the window in which a reader can observe a half-written
    capture. Production tests leave it at zero.
    """

    __slots__ = ("_out", "_path", "_staging", "_started")

    _out: Path
    _path: Path
    _staging: Path
    _started: Path

    def __new__(cls, bin_dir: Path, name: str, *, write_delay: float = 0.0) -> Self:
        self = super().__new__(cls)
        self._path = bin_dir / name
        self._out = bin_dir.parent / f"{name}.argv"
        self._started = bin_dir.parent / f"{name}.started"
        self._staging = bin_dir.parent / f"{name}.staging"
        self._staging.mkdir()
        self._path.write_text(self._script(write_delay), encoding="utf-8")
        _make_executable(self._path)
        return self

    def _script(self, write_delay: float) -> str:
        # A shell redirect creates and truncates the target before the command
        # writes to it, so a reader that sees the file can still read it empty.
        # The capture is staged in its own directory, then hard-linked into
        # place: link(2) publishes the file atomically with its content and
        # refuses to clobber an existing capture, so a second spawn fails
        # loudly instead of silently replacing the first one's argv.
        # set -e stops a failed write from publishing an empty capture; the
        # started marker lets argv() tell a failed run from one that never ran.
        staging = f"{self._staging}/$$.tmp"
        return (
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            f'touch "{self._started}"\n'
            f'exec > "{staging}"\n'
            f"sleep {write_delay}\n"
            "printf '%s\\n' \"$@\"\n"
            "exec >&-\n"
            f'ln "{staging}" "{self._out}"\n'
            f'rm "{staging}"\n'
        )

    @property
    def path(self) -> Path:
        return self._path

    @property
    def staging_dir(self) -> Path:
        return self._staging

    def argv(self, *, timeout: float = 5.0, interval: float = 0.05) -> list[str]:
        """Return the captured argv, one argument per line, once published."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._out.exists():
                return self._out.read_text(encoding="utf-8").splitlines()
            time.sleep(interval)
        raise self._timeout_error(timeout)

    def _timeout_error(self, timeout: float) -> TimeoutError:
        if not self._started.exists():
            msg = f"{self._out} did not appear within {timeout}s (stub never invoked)"
            return TimeoutError(msg)
        msg = (
            f"{self._path.name} stub started but did not publish its capture "
            f"{self._out} within {timeout}s; {self._staging_report()}. Its "
            "stderr goes to LUX_APPLET_LOG when the hook spawns it."
        )
        return TimeoutError(msg)

    def _staging_report(self) -> str:
        # The diagnostic must survive whatever broke the stub, including a
        # staging path that is no longer a directory.
        if not self._staging.is_dir():
            return f"staging path {self._staging} is not a directory"
        leftovers = sorted(p.name for p in self._staging.iterdir())
        return f"staging leftovers in {self._staging}: {leftovers or 'none'}"


def _make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _make_named_binary(tmp_path: Path, name: str) -> Path:
    """Copy the real `bash` binary to *name* so its `ps` comm matches *name*.

    `ps -o comm=` reports the basename of the execve'd file, not a script's
    shebang target — invoking `bash script.sh` always reports comm `bash`.
    Renaming the binary itself is the only way to control what `ps -o comm=`
    reports.
    """
    bash_path = shutil.which("bash")
    assert bash_path is not None, "bash must be on PATH to build the fixture"
    dest = tmp_path / name
    shutil.copy(bash_path, dest)
    _make_executable(dest)
    return dest


def _run_tree(tmp_path: Path, *, claude_comm: str) -> tuple[int, int, int]:
    """Spawn claude(comm=claude_comm) -> wrapper -> session-start.sh.

    Returns (claude_pid, wrapper_pid, resolved_session_pid).
    """
    relay_sh = tmp_path / "relay.sh"
    relay_sh.write_text(_RELAY_SH, encoding="utf-8")
    _make_executable(relay_sh)

    claude_bin = _make_named_binary(tmp_path, claude_comm)

    stub_bin = tmp_path / "stubbin"
    stub_bin.mkdir()
    stub = ArgvCaptureStub(stub_bin, "lux-beads")

    fake_home = tmp_path / "home"
    fake_home.mkdir()
    hook_tmpdir = tmp_path / "hooktmp"
    hook_tmpdir.mkdir()
    trace_file = tmp_path / "relay_trace.txt"

    env = dict(os.environ)
    env["HOME"] = str(fake_home)
    env["PATH"] = f"{stub_bin}:{env.get('PATH', '')}"
    env["TMPDIR"] = str(hook_tmpdir)
    env["RELAY_TRACE_FILE"] = str(trace_file)

    proc = subprocess.Popen(
        [str(claude_bin), str(relay_sh), "bash", str(relay_sh), "bash", str(_SCRIPT)],
        env=env,
    )
    claude_pid = proc.pid
    returncode = proc.wait(timeout=15)
    assert returncode == 0

    trace_lines = trace_file.read_text(encoding="utf-8").split()
    assert len(trace_lines) == 2, trace_lines
    wrapper_pid = int(trace_lines[1])

    stub_args = stub.argv()
    assert stub_args[:1] == ["--session-pid"], stub_args
    resolved_session_pid = int(stub_args[1])

    return claude_pid, wrapper_pid, resolved_session_pid


class TestResolvesTheRealSessionAcrossTheWrapper:
    def test_watches_the_grandparent_when_it_looks_like_claude(
        self, tmp_path: Path
    ) -> None:
        claude_pid, wrapper_pid, resolved = _run_tree(tmp_path, claude_comm="claude")
        assert resolved == claude_pid
        assert resolved != wrapper_pid

    def test_falls_back_to_the_wrapper_when_the_grandparent_is_unrecognized(
        self, tmp_path: Path
    ) -> None:
        claude_pid, wrapper_pid, resolved = _run_tree(
            tmp_path, claude_comm="not-recognized"
        )
        assert resolved == wrapper_pid
        assert resolved != claude_pid

    def test_rejects_a_near_miss_name_that_merely_contains_claude(
        self, tmp_path: Path
    ) -> None:
        """A substring match (`*claude*`) would wrongly trust this ancestor.

        `not-claude` contains the literal string "claude" but is not the real
        Claude Code process, so the exact-match check must reject it and fall
        back to the wrapper — the same fail-safe outcome as any other
        unrecognized ancestor.
        """
        claude_pid, wrapper_pid, resolved = _run_tree(
            tmp_path, claude_comm="not-claude"
        )
        assert resolved == wrapper_pid
        assert resolved != claude_pid


class TestArgvCaptureStub:
    def test_argv_waits_for_the_write_not_just_the_file(self, tmp_path: Path) -> None:
        """A reader polling a slow stub never sees a half-written capture.

        The delay sits between the stub opening its output and writing the
        argv: the window in which a reader that trusts the file's existence
        reads it empty.
        """
        stub_bin = tmp_path / "stubbin"
        stub_bin.mkdir()
        stub = ArgvCaptureStub(stub_bin, "lux-beads", write_delay=0.5)
        with subprocess.Popen([str(stub.path), "--session-pid", "4242"]) as proc:
            argv = stub.argv()
            returncode = proc.wait(timeout=5)
        assert returncode == 0
        assert argv == ["--session-pid", "4242"]

    def test_argv_keeps_one_argument_per_line(self, stub: ArgvCaptureStub) -> None:
        """An argument containing whitespace comes back as one argument."""
        assert subprocess.run([str(stub.path), "a b", "c"], check=False).returncode == 0
        assert stub.argv() == ["a b", "c"]

    def test_argv_times_out_when_the_stub_never_runs(
        self, stub: ArgvCaptureStub
    ) -> None:
        with pytest.raises(TimeoutError, match="stub never invoked"):
            stub.argv(timeout=0.2)

    def test_argv_reports_a_stub_that_started_but_failed(
        self, stub: ArgvCaptureStub
    ) -> None:
        """A stub that cannot write its capture fails fast and is named as such.

        A regular file where the staging directory should be makes the stub's
        output redirect fail with ENOTDIR after it has started — for every
        user, root included, unlike a permission bit. The stub must exit
        non-zero, publish nothing, and be reported as started-but-failed
        rather than never invoked.
        """
        stub.staging_dir.rmdir()
        stub.staging_dir.write_text("not a directory\n", encoding="utf-8")
        result = subprocess.run([str(stub.path), "x"], check=False)
        assert result.returncode != 0
        with pytest.raises(TimeoutError, match="started but did not publish"):
            stub.argv(timeout=0.2)

    def test_a_second_invocation_fails_rather_than_overwrite(
        self, stub: ArgvCaptureStub
    ) -> None:
        """A duplicate spawn is loud: the second run fails, the first capture stays."""
        assert subprocess.run([str(stub.path), "first"], check=False).returncode == 0
        second = subprocess.run([str(stub.path), "second"], check=False)
        assert second.returncode != 0
        assert stub.argv() == ["first"]


@pytest.fixture
def stub(tmp_path: Path) -> ArgvCaptureStub:
    stub_bin = tmp_path / "stubbin"
    stub_bin.mkdir()
    return ArgvCaptureStub(stub_bin, "lux-beads")
