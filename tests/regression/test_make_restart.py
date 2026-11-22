"""Exercise the restart recipe without installing or stopping local services."""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("installed", "running", "pty_exit_code", "before", "after", "new_socket", "error"),
    [
        (False, False, 0, None, None, False, ""),
        (True, False, 0, None, None, False, ""),
        (True, True, 0, 101, 102, True, ""),
        (True, True, 1, 101, None, False, "luxd-pty restart failed"),
        (False, True, 0, 101, None, False, "luxd-pty is not installed"),
        (True, True, 0, 101, None, True, "luxd-pty did not come back"),
        (True, True, 0, 101, 101, False, "luxd-pty did not come back"),
        (True, True, 0, None, 101, False, "luxd-pty did not come back"),
        (True, True, 0, None, 102, True, ""),
    ],
    ids=[
        "absent",
        "stopped",
        "ready",
        "restart-failed",
        "missing-config",
        "not-ready",
        "same-pid",
        "same-socket-with-unknown-owner",
        "new-socket-with-unknown-owner",
    ],
)
def test_make_restart_restarts_pty_and_surfaces_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    installed: bool,
    running: bool,
    pty_exit_code: int,
    before: int | None,
    after: int | None,
    new_socket: bool,
    error: str,
) -> None:
    calls = tmp_path / "calls"
    lux = tmp_path / "lux"
    lux.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$LUX_CALLS"\n')
    lux.chmod(0o700)
    uv = tmp_path / "uv"
    uv.write_text(
        '#!/bin/sh\n[ "$#" = 6 ] && [ "$1" = run ] && [ "$5" = python ] || exit 99\n'
        'exec "$PYTEST_PYTHON" "$PTY_TEST_ENTRY" "$6"\n'
    )
    uv.chmod(0o700)
    entry = tmp_path / "entry.py"
    entry.write_text(
        "import os, runpy, sys\n"
        "from argparse import ArgumentParser\n"
        "from itertools import chain, count, repeat\n"
        "from types import SimpleNamespace\n"
        "from unittest.mock import Mock\n"
        "from punt_lux.ptyd.entry_runtime import DaemonOptions\n"
        "main = runpy.run_path(sys.argv[1])['main']\n"
        "owner = Mock()\n"
        "before = int(os.environ['PTY_BEFORE_PID']) or None\n"
        "after = int(os.environ['PTY_AFTER_PID']) or None\n"
        "socket_changed = os.environ['PTY_NEW_SOCKET'] == 'yes'\n"
        "socket_id = (1, 2, 2) if socket_changed else (1, 1, 1)\n"
        "identity = Mock(side_effect=chain([(1, 1, 1)], repeat(socket_id)))\n"
        "owner.return_value.pid.side_effect = chain([before, before], repeat(after))\n"
        "clock = SimpleNamespace(monotonic=count().__next__, sleep=lambda _: None)\n"
        "main.__globals__.update(SocketOwner=owner, time=clock, _WAIT_SECONDS=3, "
        "_socket_identity=identity)\n"
        "result = main()\n"
        "if owner.called:\n"
        "    sys.argv = [sys.argv[1]]\n"
        "    expected = DaemonOptions.parse(ArgumentParser()).socket\n"
        "    owner.assert_called_once_with(expected)\n"
        "    for call in identity.call_args_list:\n"
        "        assert call.args == (expected,)\n"
        "raise SystemExit(result)\n"
    )
    if platform.system() == "Darwin":
        supervisor = tmp_path / "launchctl"
        registration = tmp_path / "Library/LaunchAgents/com.punt-labs.luxd-pty.plist"
        probe = "list com.punt-labs.luxd-pty"
        restart = f"kickstart -k gui/{os.getuid()}/com.punt-labs.luxd-pty"
    else:
        supervisor = tmp_path / "systemctl"
        registration = tmp_path / ".config/systemd/user/luxd-pty.service"
        probe = "--user is-active luxd-pty"
        restart = "--user restart luxd-pty"
    supervisor.write_text(
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$LUX_CALLS"\n'
        'if [ "$1" = list ] || [ "$2" = is-active ]; then\n'
        '    if [ "$PTY_RUNNING" = yes ]; then echo active; exit 0; fi\n'
        "    echo inactive; exit 3\n"
        'fi\nexit "$PTY_EXIT_CODE"\n'
    )
    supervisor.chmod(0o700)
    if installed:
        registration.parent.mkdir(parents=True)
        registration.touch()
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setenv("LUX_CALLS", str(calls))
    monkeypatch.setenv("PTY_RUNNING", "yes" if running else "no")
    monkeypatch.setenv("PTY_EXIT_CODE", str(pty_exit_code))
    monkeypatch.setenv("PTY_BEFORE_PID", str(before or 0))
    monkeypatch.setenv("PTY_AFTER_PID", str(after or 0))
    monkeypatch.setenv("PTY_NEW_SOCKET", "yes" if new_socket else "no")
    monkeypatch.setenv("PTY_TEST_ENTRY", str(entry))
    monkeypatch.setenv("PYTEST_PYTHON", sys.executable)

    result = subprocess.run(
        ["/usr/bin/make", "-o", "install", "restart"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )

    expected = ["hub restart", "display restart", probe]
    if running and installed:
        expected.append(restart)
    assert calls.read_text().splitlines() == expected
    if error:
        assert result.returncode != 0
        assert error in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        if not running:
            assert "skipping restart" in result.stdout
        else:
            assert "luxd-pty restarted." in result.stdout
    assert registration.exists() == installed
