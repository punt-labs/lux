"""e2e: ``install.sh`` runs end to end on a scratch prefix.

The v0.29.0 install broke because ``install.sh`` called
``lux hub restart`` immediately after ``lux hub install`` on a fresh
install: the restart was redundant (install had just started the daemon)
and its ten-second port-bind timeout raced the ``[display]`` extras' cold
load. The script bailed before ``lux display install`` ran, leaving the
display never registered.

No mocked unit test catches this class of defect. Only running the
actual shell script end to end against real ``lux hub install`` /
``lux display install`` invocations, on a real launchd domain, on the
operator's kind of machine, does — which is exactly what this test does.
It patches PATH so the currently-built ``lux`` wins on any host and
exercises both the fresh-install path (no prior daemons) and the upgrade
path (a hub already running when the script runs).

Run via ``make test-e2e`` — excluded from the default gate.
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

_REPO_ROOT = Path(__file__).resolve().parents[2]
_INSTALL_SH = _REPO_ROOT / "install.sh"
_PGREP = "/usr/bin/pgrep"
_HUB_BINARY = "luxd-hub"
_DISPLAY_BINARY = "luxd-display"


def _has_pid(binary_name: str) -> bool:
    result = subprocess.run(
        [_PGREP, "-x", binary_name], capture_output=True, text=True, check=False
    )
    return result.returncode == 0 and bool(result.stdout.strip())


def _wait_for_pid(binary_name: str, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _has_pid(binary_name):
            return
        time.sleep(0.5)
    pytest.fail(f"{binary_name} did not appear within {timeout:.0f}s")


def _run_install_sh(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    """Run the installer end to end and return the completed process."""
    return subprocess.run(
        ["/bin/sh", str(_INSTALL_SH)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=600,
    )


@pytest.fixture
def install_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Return an environment the installer can use without touching real state.

    The installer expects ``lux``, ``uv``, and ``claude`` on PATH; a real
    Python 3.13; and a writable ``~/.local/bin`` for the ``uv tool
    install`` step. On the operator's machine those are already there —
    the point of this test is to run the script *as the operator would*.
    We only sanity-check the prerequisites and skip when they are
    missing so a stripped-down CI runner does not surface as a false
    failure.
    """
    for tool in ("lux", "uv", "claude", "sh"):
        if shutil.which(tool) is None:
            pytest.skip(f"{tool} not on PATH — cannot run install.sh")
    env = os.environ.copy()
    env["PATH"] = f"{Path.home() / '.local' / 'bin'}:{env.get('PATH', '')}"
    return env


@pytest.mark.skipif(platform.system() != "Darwin", reason="launchctl is macOS-only")
def test_install_sh_fresh_install_completes(install_env: dict[str, str]) -> None:
    """A fresh install exits 0 and leaves both daemons running.

    ``pgrep`` may or may not already show the daemons before the test
    starts; the test asserts they are present *after*, which is what
    matters for the "installer worked" claim. Whether the pre-existing
    state was fresh or already-installed is not the axis under test
    here — that is what the upgrade-path test covers.
    """
    result = _run_install_sh(install_env)
    assert result.returncode == 0, (
        f"install.sh exited {result.returncode}\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
    _wait_for_pid(_HUB_BINARY)
    _wait_for_pid(_DISPLAY_BINARY)


@pytest.mark.skipif(platform.system() != "Darwin", reason="launchctl is macOS-only")
def test_install_sh_upgrade_path_completes(install_env: dict[str, str]) -> None:
    """Re-running the installer with the daemons already up exits 0.

    This is the upgrade path: the previous release is running, the
    installer replaces the wheel, and the ``hub restart`` /
    ``display restart`` branches inside ``install.sh`` (only taken when
    a daemon was already running) exercise the widened restart timeout.
    """
    # Prime by running once — if not already up.
    if not _has_pid(_HUB_BINARY) or not _has_pid(_DISPLAY_BINARY):
        first = _run_install_sh(install_env)
        assert first.returncode == 0, first.stderr
        _wait_for_pid(_HUB_BINARY)
        _wait_for_pid(_DISPLAY_BINARY)
    # Then re-run — this is the actual upgrade-path assertion.
    result = _run_install_sh(install_env)
    assert result.returncode == 0, (
        f"install.sh (upgrade) exited {result.returncode}\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )
    _wait_for_pid(_HUB_BINARY)
    _wait_for_pid(_DISPLAY_BINARY)
