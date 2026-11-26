"""Structural guard: the REST transport must never be importable by name."""

from __future__ import annotations

import ast
from pathlib import Path

from tools.source_tree import SourceTree

_SRC = Path(__file__).parents[2] / "src" / "punt_lux"
_MODULES = SourceTree(_SRC.parent).modules()
_PRIVATE_NAMES = frozenset({"_RestTransport", "_SceneRestOps", "_DisplayRestOps"})
_PRIVATE_MODULE_STEMS = frozenset({"_rest_transport", "_rest_scenes", "_rest_display"})


def _imported_names(tree: ast.AST) -> set[str]:
    """Return every name a ``from`` import reads or binds in ``tree``."""
    return {
        name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
        for name in (alias.name, alias.asname)
        if name
    }


def test_aliased_private_import_is_detected() -> None:
    """Renaming a private name on import does not hide it from the guard."""
    tree = ast.parse("from ._rest_transport import _RestTransport as Transport\n")
    assert "_RestTransport" in _imported_names(tree)


def test_alias_that_binds_a_private_name_is_detected() -> None:
    """Binding some other object to a private name is caught too."""
    tree = ast.parse("from .facade import LuxClient as _RestTransport\n")
    assert "_RestTransport" in _imported_names(tree)


def _imported_modules(tree: ast.AST) -> set[str]:
    """Return the dotted path of every module ``tree`` imports."""
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            parent = node.module or ""
            modules.add(parent)
            modules.update(f"{parent}.{alias.name}" for alias in node.names)
    return modules


def _imports_private_module(tree: ast.AST) -> bool:
    return any(
        module.endswith(stem)
        for module in _imported_modules(tree)
        for stem in _PRIVATE_MODULE_STEMS
    )


def test_from_import_of_the_private_module_is_detected() -> None:
    """A ``from`` import of the transport module is caught."""
    tree = ast.parse("from punt_lux.client._rest_transport import _RestTransport\n")
    assert _imports_private_module(tree)


def test_plain_import_of_the_private_module_is_detected() -> None:
    """A plain ``import ... as`` of the transport module is caught."""
    tree = ast.parse("import punt_lux.client._rest_transport as rt\n")
    assert _imports_private_module(tree)


def test_private_module_imported_as_a_name_is_detected() -> None:
    """Importing the transport module from its package is caught."""
    for source in (
        "from punt_lux.client import _rest_transport\n",
        "from . import _rest_scenes as scenes\n",
    ):
        assert _imports_private_module(ast.parse(source)), source


def test_public_import_is_not_flagged() -> None:
    """An import of the public facade is left alone."""
    tree = ast.parse("import punt_lux.client.facade\nfrom punt_lux import LuxClient\n")
    assert not _imports_private_module(tree)


def test_private_transport_module_not_importable_from_init() -> None:
    """No __init__.py anywhere in the package re-exports a private name."""
    for init_py in (p for p in _MODULES.values() if p.name == "__init__.py"):
        imported = _imported_names(ast.parse(init_py.read_text()))
        assert imported.isdisjoint(_PRIVATE_NAMES), (
            f"{init_py} imports a private transport name -- leak reopened"
        )


def test_no_module_outside_client_imports_the_private_transport() -> None:
    """Only client/'s own modules (and its own tests) may import the transport."""
    for py_file in _MODULES.values():
        if py_file.parent.name == "client":
            continue
        assert not _imports_private_module(ast.parse(py_file.read_text())), (
            f"{py_file} imports a private transport module"
        )
