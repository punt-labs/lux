"""A background Display launch uses the executable namespace CLI."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from punt_lux.service.display_paths import DisplayPaths


@pytest.mark.parametrize("name", ["display.sock", "display socket.sock"])
def test_display_spawn_targets_the_namespace_cli(tmp_path: Path, name: str) -> None:
    socket = tmp_path / name
    assert DisplayPaths(socket)._display_argv() == [
        sys.executable,
        "-P",
        "-m",
        "punt_lux.cli",
        "display",
        "serve",
        "--socket",
        str(socket),
    ]
