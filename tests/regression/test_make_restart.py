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
    ("installed", "running", "pty_exit_code"),
    [(False, False, 0), (True, False, 0), (True, True, 0), (True, True, 1)],
)
def test_make_restart_restarts_pty_and_surfaces_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    installed: bool,
    running: bool,
    pty_exit_code: int,
) -> None:
    calls = tmp_path / "calls"
    lux = tmp_path / "lux"
    lux.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$LUX_CALLS"\n')
    lux.chmod(0o700)
    uv = tmp_path / "uv"
    uv.write_text(
        '#!/bin/sh\n[ "$#" = 6 ] && [ "$1" = run ] && [ "$5" = python ] || exit 99\n'
        'exec "$PYTEST_PYTHON" "$6"\n'
    )
    uv.chmod(0o700)
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
    if running:
        expected.append(restart)
    assert calls.read_text().splitlines() == expected
    if pty_exit_code:
        assert result.returncode != 0
        assert "luxd-pty restart failed" in result.stderr
    else:
        assert result.returncode == 0, result.stderr
        if not running:
            assert "skipping restart" in result.stdout
        else:
            assert "luxd-pty restarted." in result.stdout
    assert registration.exists() == installed
