"""Daemon imports must not require GPU, image or array packages."""

from __future__ import annotations

import subprocess
import sys

import pytest

pytest.importorskip("pyghostty")


def test_daemon_imports_with_gui_dependencies_blocked() -> None:
    code = """
import importlib.abc
import sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split('.')[0] in {'imgui_bundle', 'numpy', 'PIL', 'OpenGL'}:
            raise ModuleNotFoundError('GUI import forbidden: ' + name)
sys.meta_path.insert(0, Guard())
from punt_lux.ptyd.server import PtyServer
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr
