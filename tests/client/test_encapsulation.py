"""Structural guard: the REST transport must never be importable by name."""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).parents[2] / "src" / "punt_lux"
_PRIVATE_NAMES = frozenset({"_RestTransport", "_SceneRestOps", "_DisplayRestOps"})
_PRIVATE_MODULE_STEMS = frozenset({"_rest_transport", "_rest_scenes", "_rest_display"})


def test_private_transport_module_not_importable_from_init() -> None:
    """No __init__.py anywhere in the package re-exports a private name."""
    for init_py in _SRC.rglob("__init__.py"):
        tree = ast.parse(init_py.read_text())
        imported = {
            alias.asname or alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        assert imported.isdisjoint(_PRIVATE_NAMES), (
            f"{init_py} imports a private transport name -- leak reopened"
        )


def test_no_module_outside_client_imports_the_private_transport() -> None:
    """Only client/'s own modules (and its own tests) may import the transport."""
    for py_file in _SRC.rglob("*.py"):
        if py_file.parent.name == "client":
            continue
        tree = ast.parse(py_file.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not any(
                    node.module.endswith(stem) for stem in _PRIVATE_MODULE_STEMS
                ), f"{py_file} imports the private transport module {node.module}"
