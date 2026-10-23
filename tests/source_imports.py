"""Read what a source file imports, as the dotted modules the imports resolve to."""

from __future__ import annotations

import ast
from pathlib import Path


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
