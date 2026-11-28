"""The SessionStart event sink accepts only safe launch diagnostics."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.fixture
def enabled_repo(tmp_path: Path) -> Path:
    git = shutil.which("git") or "/usr/bin/git"
    subprocess.run([git, "init", "-q", str(tmp_path)], check=True)
    marker = tmp_path / ".punt-labs/lux/enabled"
    marker.parent.mkdir(parents=True)
    marker.touch()
    return tmp_path


@pytest.mark.parametrize(
    ("scenario", "message"),
    [
        ("missing", "skipped: executable missing"),
        ("running", "skipped: already running"),
        ("probe-error", "failed: process probe error"),
        ("launch", "launched: spawned"),
        ("spawn-error", "failed: spawn error"),
    ],
)
def test_shell_records_decisions_without_standard_streams(
    enabled_repo: Path, scenario: str, message: str
) -> None:
    tmp_path = enabled_repo
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "lux").symlink_to(Path(sys.executable).parent / "lux")
    if scenario != "missing":
        applet = bin_dir / "lux-beads"
        applet.write_text("#!/bin/sh\nsleep 1\n")
        applet.chmod(0o700)
    probe = bin_dir / "pgrep"
    probe.write_text(
        f"#!/bin/sh\nexit { {'running': 0, 'probe-error': 2}.get(scenario, 1) }\n"
    )
    probe.chmod(0o700)
    script = Path(__file__).resolve().parents[2] / "plugin/hooks/session-start.sh"
    env = {**os.environ, "HOME": str(tmp_path), "PATH": f"{bin_dir}:/usr/bin:/bin"}
    if scenario == "spawn-error":
        env["BASH_FUNC_kill%%"] = "() { return 1;\n}"
    result = subprocess.run(
        ["/bin/bash", str(script)],
        input='{"hook_event_name":"SessionStart","session_id":"private-session"}',
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=enabled_repo,
        env=env,
        check=False,
    )
    assert result.returncode == 0
    path = tmp_path / ".punt-labs/lux/logs/lux.log"
    log = ""
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        log = path.read_text() if path.exists() else ""
        if f"SessionStart applet {message}" in log and (
            scenario not in ("launch", "spawn-error")
            or "launch intent: spawning" in log
        ):
            break
        time.sleep(0.01)
    assert f"SessionStart applet {message}" in log
    assert ("launch intent: spawning" in log) == (scenario in ("launch", "spawn-error"))
    if scenario in ("launch", "spawn-error"):
        assert log.index("launch intent: spawning") < log.index(message)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert str(tmp_path) not in log
    assert "private-session" not in log


@pytest.mark.slow
@pytest.mark.parametrize("logger_state", ["missing", "failing", "stalled"])
def test_logging_cannot_prevent_launch(enabled_repo: Path, logger_state: str) -> None:
    tmp_path = enabled_repo
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    if logger_state == "failing":
        lux = bin_dir / "lux"
        lux.write_text("#!/bin/sh\necho noisy\necho noisy >&2\nexit 1\n")
        lux.chmod(0o700)
    if logger_state == "stalled":
        lux = bin_dir / "lux"
        lux.write_text("#!/bin/sh\nexec sleep 60\n")
        lux.chmod(0o700)
    captured = tmp_path / "launched"
    applet = bin_dir / "lux-beads"
    applet.write_text(f"#!/bin/sh\ntouch '{captured}'\n")
    applet.chmod(0o700)
    probe = bin_dir / "pgrep"
    probe.write_text("#!/bin/sh\nexit 1\n")
    probe.chmod(0o700)
    script = Path(__file__).resolve().parents[2] / "plugin/hooks/session-start.sh"
    result = subprocess.run(
        ["/bin/bash", str(script)],
        capture_output=True,
        text=True,
        check=False,
        timeout=3,
        cwd=enabled_repo,
        env={**os.environ, "HOME": str(tmp_path), "PATH": f"{bin_dir}:/usr/bin:/bin"},
    )
    assert result.returncode == 0
    assert result.stdout == result.stderr == ""
    deadline = time.monotonic() + 5
    while not captured.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert captured.exists()
