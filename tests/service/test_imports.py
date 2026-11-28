"""Each relocated module must import without prior facade initialization."""

from __future__ import annotations

import subprocess
import sys

import pytest

_GENERIC = {
    "_atomic_write",
    "_backend_launchd",
    "_backend_systemd",
    "_backends",
    "_binary_sweep",
    "_doctor_result",
    "_launchctl",
    "_launchd_plist",
    "_legacy_sweep",
    "_legacy_sweep_launchd",
    "_legacy_sweep_systemd",
    "_platform_dispatch",
    "_port_guard",
    "_service_errors",
}


@pytest.mark.parametrize(
    "module",
    [
        "punt_lux.service",
        "punt_service",
        "punt_service.service_spec",
        *(
            f"{'punt_service' if name in _GENERIC else 'punt_lux.service'}.{name}"
            for name in (
                "_atomic_write",
                "_backend_launchd",
                "_backend_systemd",
                "_backends",
                "_binary_sweep",
                "_binary_sweep_disk",
                "_doctor_result",
                "_launchctl",
                "_launchd_plist",
                "_legacy_sweep",
                "_legacy_sweep_launchd",
                "_legacy_sweep_systemd",
                "_platform_dispatch",
                "_port_guard",
                "_service_errors",
                "service_spec",
                "_shim_ownership",
                "applet_event",
                "claude_permissions",
                "config",
                "display_mode_store",
                "display_paths",
                "display_restart",
                "doctor_checks",
                "doctor_report",
                "entry_runtime",
                "hooks",
                "hub_restart",
                "permission_rules",
                "session_start",
            )
        ),
        "punt_lux.kernel.hub_paths",
        "punt_lux.kernel.hub_defaults",
        "punt_lux.cli.repo_enablement",
    ],
)
def test_relocated_module_imports_in_fresh_process(module: str) -> None:
    result = subprocess.run(
        [sys.executable, "-c", f"import {module}"],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
