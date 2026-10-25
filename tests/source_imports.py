"""Read what a source file imports, as the dotted modules the imports resolve to."""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable


def module_name(relpath: str) -> str:
    """The dotted module a ``src``-rooted file is imported as."""
    parts = Path(relpath).with_suffix("").parts
    if parts[0] == "src":
        parts = parts[1:]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def resolved_imports(source: str, module: str, *, is_package: bool = False) -> set[str]:
    """Every dotted name ``source`` binds by import, relative imports resolved.

    ``from . import presence_writes`` in ``punt_lux.domain.hub.x`` yields both the
    package and ``punt_lux.domain.hub.presence_writes``, so a module is recognised
    whether it is imported as a module or by one of its names.
    """
    package = module.split(".") if is_package else module.split(".")[:-1]
    bound: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            bound.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = package[: len(package) - (node.level - 1)] if node.level else []
            tail = node.module.split(".") if node.module else []
            origin = ".".join([*base, *tail])
            bound.add(origin)
            bound.update(f"{origin}.{alias.name}" for alias in node.names)
    return bound


def module_file(src: Path, dotted: str) -> Path | None:
    """The source file ``dotted`` is imported from under ``src``, or ``None``."""
    base = src.joinpath(*dotted.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def import_closure(
    src: Path, roots: Iterable[str], *, within: str
) -> dict[str, frozenset[str]]:
    """The modules under ``within`` reached from ``roots``, each with what it imports.

    Every import counts, deferred or annotation-only: a module that names another
    in an import depends on it. Only edges to modules that exist under ``src`` and
    sit under ``within`` are followed and kept.
    """
    closure: dict[str, frozenset[str]] = {}
    pending = list(roots)
    while pending:
        dotted = pending.pop()
        if dotted in closure:
            continue
        path = module_file(src, dotted)
        if path is None:
            continue
        bound = resolved_imports(
            path.read_text(encoding="utf-8"),
            dotted,
            is_package=path.name == "__init__.py",
        )
        edges = frozenset(
            name
            for name in bound
            if name != dotted
            and (name == within or name.startswith(f"{within}."))
            and module_file(src, name) is not None
        )
        closure[dotted] = edges
        pending.extend(edges)
    return closure


def defining_modules(
    src: Path, *, within: str, names: Iterable[str]
) -> dict[str, frozenset[str]]:
    """Which modules under ``within`` define each of ``names``: a class, or a
    module-level assignment. The result maps each name to the modules defining it."""
    wanted = set(names)
    found: dict[str, set[str]] = {name: set() for name in wanted}
    for path in sorted(src.joinpath(*within.split(".")).rglob("*.py")):
        dotted = module_name(path.relative_to(src).as_posix())
        for node in ast.parse(path.read_text(encoding="utf-8")).body:
            defined = _defined_names(node)
            for name in wanted & defined:
                found[name].add(dotted)
    return {name: frozenset(modules) for name, modules in found.items()}


def _defined_names(node: ast.stmt) -> set[str]:
    if isinstance(node, ast.ClassDef):
        return {node.name}
    if isinstance(node, ast.Assign):
        return {t.id for t in node.targets if isinstance(t, ast.Name)}
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return {node.target.id}
    return set()
