"""ExceptionScan -- which exception classes in a source tree are frozen dataclasses."""

from __future__ import annotations

import ast
import builtins
from pathlib import Path
from typing import Self, final

__all__ = ["ExceptionScan"]


@final
class ExceptionScan:
    """Finds, by syntax alone, every class that is both an exception and frozen."""

    _classes: dict[str, tuple[tuple[str, ...], bool, str]]
    __slots__ = ("_classes",)

    def __new__(cls, root: Path) -> Self:
        self = super().__new__(cls)
        self._classes = {}
        for path in sorted(root.rglob("*.py")):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.ClassDef):
                    where = f"{path}:{node.lineno}"
                    self._classes[node.name] = (
                        tuple(self._base_name(b) for b in node.bases),
                        any(self._is_frozen(d) for d in node.decorator_list),
                        where,
                    )
        return self

    def frozen_exceptions(self) -> list[str]:
        """Where each frozen dataclass that is an exception class is defined."""
        return [
            f"{name} at {where}"
            for name, (_, frozen, where) in sorted(self._classes.items())
            if frozen and self._is_exception(name, set())
        ]

    def _is_exception(self, name: str, seen: set[str]) -> bool:
        if name in seen:
            return False
        seen.add(name)
        builtin = getattr(builtins, name, None)
        if isinstance(builtin, type):
            return issubclass(builtin, BaseException)
        entry = self._classes.get(name)
        return entry is not None and any(self._is_exception(b, seen) for b in entry[0])

    @staticmethod
    def _base_name(base: ast.expr) -> str:
        if isinstance(base, ast.Attribute):
            return base.attr
        if isinstance(base, ast.Name):
            return base.id
        return ""

    @staticmethod
    def _is_frozen(decorator: ast.expr) -> bool:
        return (
            isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Name | ast.Attribute)
            and getattr(decorator.func, "id", getattr(decorator.func, "attr", ""))
            == "dataclass"
            and any(
                kw.arg == "frozen"
                and isinstance(kw.value, ast.Constant)
                and kw.value.value is True
                for kw in decorator.keywords
            )
        )
