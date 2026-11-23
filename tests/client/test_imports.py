"""The client SDK initializes independently without blocking DNS or old aliases."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src"
_CLIENT = _SRC / "punt_lux" / "client"
_MODULES = sorted(
    ".".join(path.relative_to(_SRC).with_suffix("").parts).removesuffix(".__init__")
    for path in _CLIENT.rglob("*.py")
)
_OLD_MODULES = [
    "punt_lux.hub_client",
    "punt_lux.rest_transport",
    "punt_lux.rest_http_call",
    "punt_lux.rest_loopback",
    "punt_lux.rest_reply",
    "punt_lux.rest_error_body",
    "punt_lux.identity_headers",
    "punt_lux.header_value",
    "punt_lux.cli_identity",
    "punt_lux.hub.client_identity",
    "punt_lux.hub.applet_name_format",
]


@pytest.mark.parametrize("module", _MODULES)
def test_client_module_imports_in_fresh_process(module: str) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from unittest.mock import patch; "
                "guard = patch('socket.getfqdn', side_effect=AssertionError('DNS')); "
                "guard.start(); "
                f"import {module}"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("module", _OLD_MODULES)
def test_moved_module_has_no_alias_in_fresh_process(module: str) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import importlib.util; "
                f"assert importlib.util.find_spec('{module}') is None"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
