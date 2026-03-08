"""AST-based warning scanner for render function source code.

NOT a security boundary — a user-facing signal shown in the consent dialog.
The real security is the consent prompt itself.  The scanner flags suspicious
imports, builtin calls, and attribute access so the user can make an informed
decision.
"""

from __future__ import annotations

import ast

# Modules that suggest system-level access
_SUSPICIOUS_MODULES: frozenset[str] = frozenset(
    {
        "ctypes",
        "http",
        "os",
        "pathlib",
        "requests",
        "shutil",
        "signal",
        "socket",
        "subprocess",
        "urllib",
    }
)

# Builtin function names that suggest dangerous operations
_SUSPICIOUS_CALLS: frozenset[str] = frozenset(
    {
        "__import__",
        "compile",
        "delattr",
        "eval",
        "exec",
        "getattr",
        "globals",
        "locals",
        "open",
        "setattr",
    }
)

# Attribute-access roots that suggest system access
_SUSPICIOUS_ATTRS: frozenset[str] = frozenset(
    {
        "os",
        "subprocess",
        "sys",
    }
)


class _WarningVisitor(ast.NodeVisitor):
    """Walk an AST and collect warning strings."""

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            top = alias.name.split(".")[0]
            if top in _SUSPICIOUS_MODULES:
                self.warnings.append(
                    f"Imports `{alias.name}` — may access system resources"
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            top = node.module.split(".")[0]
            if top in _SUSPICIOUS_MODULES:
                self.warnings.append(
                    f"Imports from `{node.module}` — may access system resources"
                )
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name):
            if node.func.id in _SUSPICIOUS_CALLS:
                self.warnings.append(f"Calls `{node.func.id}()` — review carefully")
        elif (
            isinstance(node.func, ast.Attribute)
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id in _SUSPICIOUS_ATTRS
        ):
            self.warnings.append(
                f"Accesses `{node.func.value.id}.{node.func.attr}` "
                f"— may access system resources"
            )
        self.generic_visit(node)


def check_source(source: str) -> list[str]:
    """Parse Python source and return a list of warning strings.

    Returns an empty list if the source is clean.  Returns a syntax error
    warning if the source fails to parse (the compile step will catch the
    actual error).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ["Source has syntax errors — will fail at compile time"]

    visitor = _WarningVisitor()
    visitor.visit(tree)
    return visitor.warnings
