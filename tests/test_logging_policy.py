"""Disallow process-unsafe logging configuration in production Python."""

from __future__ import annotations

import ast
from pathlib import Path

_SOURCE = Path(__file__).resolve().parents[1] / "src"
_BANNED = {"basicConfig", "RotatingFileHandler", "TimedRotatingFileHandler"}


def _banned_name(node: ast.AST) -> str:
    match node:
        case ast.alias(name=name) | ast.Name(id=name) | ast.Attribute(attr=name):
            return name.rsplit(".", 1)[-1]
        case ast.Constant(value=str() as value):
            return value.rsplit(".", 1)[-1]
        case _:
            return ""


def test_source_uses_no_forbidden_logging_setup() -> None:
    violations = [
        f"{path.relative_to(_SOURCE)}:{getattr(node, 'lineno', '?')}: {name}"
        for path in sorted(_SOURCE.rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
        if (name := _banned_name(node)) in _BANNED
    ]
    assert not violations, "\n".join(violations)
