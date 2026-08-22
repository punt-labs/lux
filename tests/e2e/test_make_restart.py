"""Fidelity-control e2e: the operator's actual ``make restart`` sequence.

lux-j169 renamed the hub disk binary (``luxd`` -> ``luxd-hub``) but the
Makefile's ``restart`` target kept running ``launchctl kickstart -k`` — which
never rewrites a launchd plist, so it hung forever waiting on the program at
the DELETED ``~/.local/bin/luxd`` path. No mocked unit test can catch this
class of defect: it requires a real ``uv tool install``, a real
``lux hub install`` / ``lux display install`` (which regenerate the plist via
:meth:`~punt_lux.service.ServiceManager.install`), and a real
``launchctl print`` against the resulting service, on the real machine.

This is the acceptance gate for lux-5i3n: it would have failed the moment
lux-j169 merged with the display's ``binary_name`` still ``lux``. It never
touches a scratch fixture — it drives the real
``~/.local/bin/luxd-hub`` / ``~/.local/bin/luxd-display`` shims and the real
``com.punt-labs.luxd-hub`` / ``com.punt-labs.luxd-display`` launchd services,
exactly as ``make restart`` does on the operator's machine.

Run via ``make test-e2e`` -- excluded from the default ``make test`` gate.
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
_UID = os.getuid()
_HUB_LABEL = "com.punt-labs.luxd-hub"
_DISPLAY_LABEL = "com.punt-labs.luxd-display"
_HUB_BINARY = "luxd-hub"
_DISPLAY_BINARY = "luxd-display"


def _run(*args: str, timeout: float = 300.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=_REPO_ROOT, capture_output=True, text=True, timeout=timeout
    )


_PGREP = "/usr/bin/pgrep"


def _wait_for_pid(binary_name: str, timeout: float = 60.0) -> int:
    """Poll ``pgrep -x`` until ``binary_name`` appears; fail loud on timeout.

    ``pgrep`` ships at a fixed path on every macOS install (this test is
    ``skipif``'d to Darwin only). ``shutil.which("pgrep")`` is not reliably
    resolvable across every CI shell env or under ``uv run`` if ``/usr/bin``
    is missing from PATH; calling the absolute path sidesteps that PATH
    dependency entirely rather than papering over it with a PATH extension
    in the workflow.

    The 60s timeout (was 20s) accounts for GitHub's ``macos-latest`` runner
    cold-starting launchd's GUI-domain service: loading the native ImGui/GLFW
    stack and creating a GPU context on a shared CI VM measurably outlasts the
    same sequence on a warm local machine.
    """
    assert Path(_PGREP).exists(), f"{_PGREP} is not present on this Darwin host"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = subprocess.run(
            [_PGREP, "-x", binary_name], capture_output=True, text=True
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip().splitlines()[0])
        time.sleep(0.5)
    pytest.fail(f"{binary_name} did not appear in the process table within {timeout}s")


@pytest.mark.skipif(platform.system() != "Darwin", reason="launchctl is macOS-only")
@pytest.mark.skipif(shutil.which("uv") is None, reason="uv is not on PATH")
def test_make_restart_sequence_installs_and_starts_both_services() -> None:
    """Run the exact sequence 'make restart' performs and verify both services.

    Builds the real wheel, installs it with the display extra, runs
    'lux hub install' and 'lux display install' (the fix -- these regenerate
    the launchd plists; a bare 'launchctl kickstart' does not), then asserts
    both plists reference the CURRENT binaries and both processes are alive.
    """
    build = _run("make", "build")
    assert build.returncode == 0, build.stderr

    wheels = sorted((_REPO_ROOT / "dist").glob("punt_lux-*.whl"))
    assert wheels, "make build did not produce a wheel in dist/"
    wheel = wheels[-1]

    install = _run("uv", "tool", "install", "--force", f"{wheel}[display]")
    assert install.returncode == 0, install.stderr
    assert _HUB_BINARY in install.stdout or _HUB_BINARY in install.stderr
    assert _DISPLAY_BINARY in install.stdout or _DISPLAY_BINARY in install.stderr

    hub_install = _run("lux", "hub", "install")
    assert hub_install.returncode == 0, hub_install.stderr

    display_install = _run("lux", "display", "install")
    assert display_install.returncode == 0, display_install.stderr

    home = Path.home()
    hub_bin = home / ".local" / "bin" / _HUB_BINARY
    display_bin = home / ".local" / "bin" / _DISPLAY_BINARY
    assert hub_bin.exists(), f"{hub_bin} missing after install"
    assert display_bin.exists(), f"{display_bin} missing after install"

    hub_print = _run("launchctl", "print", f"gui/{_UID}/{_HUB_LABEL}")
    assert str(hub_bin) in hub_print.stdout, (
        f"plist for {_HUB_LABEL} does not reference {hub_bin}:\n{hub_print.stdout}"
    )

    display_print = _run("launchctl", "print", f"gui/{_UID}/{_DISPLAY_LABEL}")
    assert str(display_bin) in display_print.stdout, (
        f"plist for {_DISPLAY_LABEL} does not reference "
        f"{display_bin}:\n{display_print.stdout}"
    )

    hub_pid = _wait_for_pid(_HUB_BINARY)
    display_pid = _wait_for_pid(_DISPLAY_BINARY)
    assert hub_pid > 0
    assert display_pid > 0

    hub_doctor = _run("lux", "hub", "doctor")
    assert hub_doctor.returncode == 0, hub_doctor.stdout + hub_doctor.stderr

    display_doctor = _run("lux", "display", "doctor")
    assert display_doctor.returncode == 0, display_doctor.stdout + display_doctor.stderr
