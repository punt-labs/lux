"""Fidelity-control e2e: LaunchdLegacySweep against REAL launchd/systemd.

No mock can reproduce the cross-domain no-op that shipped the lux-ehzy
bug -- ``launchctl unload -w`` silently failing to deregister a
``bootstrap``-loaded job is a property of the real launchd subsystem, not
of this codebase's logic (docs/architecture/service-lifecycle-migration.md
§7.3). This module bootstraps a real, disposable scratch label/unit,
proves the sweep actually deregisters it with the real supervisor, and
tears it down unconditionally even on assertion failure.

Run via ``make test-e2e`` -- excluded from the default ``make test`` gate.
"""

from __future__ import annotations

import os
import platform
import subprocess
import textwrap
import uuid
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path

import pytest

from punt_lux._legacy_sweep_launchd import LaunchdLegacySweep
from punt_lux._legacy_sweep_systemd import SystemdLegacySweep
from punt_lux.service import HUB_SPEC

pytestmark = pytest.mark.e2e


def _scratch_suffix() -> str:
    return f"{os.getpid()}-{uuid.uuid4().hex[:8]}"


@pytest.fixture
def scratch_launchd_label() -> Iterator[str]:
    """Bootstrap a real, disposable launchd label; boot it out on teardown."""
    label = f"com.punt-labs.lux-test-{_scratch_suffix()}"
    agents_dir = Path.home() / "Library" / "LaunchAgents"
    agents_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    plist_path = agents_dir / f"{label}.plist"
    domain = f"gui/{os.getuid()}"

    plist_path.write_text(
        textwrap.dedent(f"""\
            <?xml version="1.0" encoding="UTF-8"?>
            <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
              "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
            <plist version="1.0">
            <dict>
                <key>Label</key>
                <string>{label}</string>
                <key>ProgramArguments</key>
                <array>
                    <string>/bin/sleep</string>
                    <string>300</string>
                </array>
                <key>RunAtLoad</key>
                <true/>
                <key>KeepAlive</key>
                <false/>
            </dict>
            </plist>
        """)
    )
    subprocess.run(
        ["launchctl", "bootstrap", domain, str(plist_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        yield label
    finally:
        subprocess.run(
            ["launchctl", "bootout", f"{domain}/{label}"],
            check=False,
            capture_output=True,
            text=True,
        )
        plist_path.unlink(missing_ok=True)


@pytest.fixture
def scratch_systemd_unit() -> Iterator[str]:
    """Enable a real, disposable systemd user unit; disable it on teardown."""
    unit = f"lux-test-{_scratch_suffix()}"
    units_dir = Path.home() / ".config" / "systemd" / "user"
    units_dir.mkdir(parents=True, exist_ok=True)
    unit_path = units_dir / f"{unit}.service"

    unit_path.write_text(
        textwrap.dedent("""\
            [Unit]
            Description=lux legacy-sweep e2e scratch unit

            [Service]
            ExecStart=/bin/sleep 300

            [Install]
            WantedBy=default.target
        """)
    )
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    subprocess.run(
        ["systemctl", "--user", "enable", "--now", f"{unit}.service"],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        yield unit
    finally:
        subprocess.run(
            ["systemctl", "--user", "disable", "--now", f"{unit}.service"],
            check=False,
            capture_output=True,
            text=True,
        )
        unit_path.unlink(missing_ok=True)
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)


@pytest.mark.skipif(platform.system() != "Darwin", reason="launchd is macOS-only")
def test_sweep_deregisters_a_real_bootstrap_loaded_label(
    scratch_launchd_label: str,
) -> None:
    domain = f"gui/{os.getuid()}"
    target = f"{domain}/{scratch_launchd_label}"

    # Setup sanity: the scratch label really is loaded before the sweep.
    setup_check = subprocess.run(
        ["launchctl", "print", target], capture_output=True, text=True, check=False
    )
    assert setup_check.returncode == 0, (
        f"scratch label {scratch_launchd_label} did not bootstrap: {setup_check.stderr}"
    )

    spec = replace(HUB_SPEC, legacy_launchd_labels=(scratch_launchd_label,))
    sweep = LaunchdLegacySweep(spec)

    report = sweep.sweep()

    assert report.all_clean

    # The fidelity check this design exists to prove: a bootstrap-registered
    # service is actually gone from the real launchd job table, not just
    # file-absent.
    post_check = subprocess.run(
        ["launchctl", "print", target], capture_output=True, text=True, check=False
    )
    assert post_check.returncode != 0, (
        f"scratch label {scratch_launchd_label} is STILL registered with "
        "launchd after sweep() reported it clean"
    )


@pytest.mark.skipif(platform.system() != "Linux", reason="systemd is Linux-only")
def test_sweep_deregisters_a_real_systemd_unit(scratch_systemd_unit: str) -> None:
    unit_service = f"{scratch_systemd_unit}.service"

    setup_check = subprocess.run(
        ["systemctl", "--user", "status", unit_service],
        capture_output=True,
        text=True,
        check=False,
    )
    assert setup_check.returncode != 4, (
        f"scratch unit {unit_service} was not enabled: {setup_check.stderr}"
    )

    spec = replace(HUB_SPEC, legacy_systemd_units=(scratch_systemd_unit,))
    sweep = SystemdLegacySweep(spec)

    report = sweep.sweep()

    assert report.all_clean

    post_check = subprocess.run(
        ["systemctl", "--user", "status", unit_service],
        capture_output=True,
        text=True,
        check=False,
    )
    assert post_check.returncode == 4, (
        f"scratch unit {unit_service} is STILL known to systemd after "
        "sweep() reported it clean"
    )
