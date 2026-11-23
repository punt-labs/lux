"""The entire client distribution is closed even over annotation-only imports."""

from __future__ import annotations

import ast
import sys
from importlib.util import resolve_name
from pathlib import Path

import pytest

from tools.source_tree import SourceTree

_ROOT = Path(__file__).resolve().parents[1]
_SOURCE = _ROOT / "packages/punt-lux-client/src"
_PACKAGES = {"client", "wire", "kernel", "applets"}
_FORBIDDEN = {
    *(
        f"punt_lux.{name}"
        for name in (
            "hub",
            "display",
            "pty",
            "service",
            "trust",
            "commands",
            "beads",
            "operations",
            "rest",
            "tools",
            "cli",
        )
    ),
    "fastapi",
    "starlette",
    "mcp",
    "mcp_types",
    "fastmcp",
    "punt_service",
}


def _module(path: Path) -> str:
    parts = path.relative_to(_SOURCE).with_suffix("").parts
    return ".".join(parts[:-1] if path.stem == "__init__" else parts)


def _imports(path: Path) -> set[str]:
    module = _module(path)
    package = module if path.stem == "__init__" else module.rpartition(".")[0]
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            origin = node.module or ""
            if node.level:
                origin = resolve_name("." * node.level + origin, package)
            names.add(origin)
            names.update(f"{origin}.{alias.name}" for alias in node.names)
        elif (
            isinstance(node, ast.Call)
            and ast.unparse(node.func) in {"importlib.import_module", "__import__"}
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            names.add(node.args[0].value)
    return names


def test_headless_static_import_closure_includes_type_checking_branches() -> None:
    modules = SourceTree(_ROOT / "src").modules()
    pending = {name for name in modules if name.split(".")[1] in _PACKAGES}
    assert pending
    visited: set[str] = set()
    while pending:
        module = pending.pop()
        if module in visited:
            continue
        visited.add(module)
        for target in _imports(modules[module]):
            assert not any(
                target == prefix or target.startswith(prefix + ".")
                for prefix in _FORBIDDEN
            ), f"{module} imports {target}"
            parts = target.split(".")
            pending.update(
                parent
                for size in range(2, len(parts) + 1)
                if (parent := ".".join(parts[:size])) in modules
                and parent not in visited
            )


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("", set()),
        ("if TYPE_CHECKING:\n    import starlette.requests\n", {"starlette.requests"}),
        ("from .peer import Host", {"portion.peer", "portion.peer.Host"}),
        ("importlib.import_module('mcp.server')", {"mcp.server"}),
    ],
)
def test_ast_import_inventory_includes_guarded_relative_and_dynamic_imports(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source: str,
    expected: set[str],
) -> None:
    monkeypatch.setattr(sys.modules[__name__], "_SOURCE", tmp_path)
    package = tmp_path / "portion"
    package.mkdir()
    module = package / "leaf.py"
    module.write_text(source)
    assert _imports(module) == expected


def test_invalid_ast_is_not_silently_ignored(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys.modules[__name__], "_SOURCE", tmp_path)
    module = tmp_path / "broken.py"
    module.write_text("if :")
    with pytest.raises(SyntaxError):
        _imports(module)
