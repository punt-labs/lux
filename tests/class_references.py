"""Resolve which calls in a source file construct, or reach through, a given class.

A construction-site guard that counts the spelling ``Name(...)`` is evaded by a
rename. This follows the class through ``from m import Name as X``, a module
alias (``import m as mod`` then ``mod.Name``), ``getattr(mod, "Name")`` and any
assignment of those to another name, so a guard counts what a call builds and not
how the caller chose to write it.
"""

from __future__ import annotations

import ast
from typing import Self, final

__all__ = ["ClassReferences", "aliased_constructions"]


def aliased_constructions(module: str, name: str) -> tuple[str, ...]:
    """Sources that each build ``module.name`` once, one in every aliased spelling.

    Planted into a guard, each must be counted: a guard that misses one can be
    walked around by renaming the import.
    """
    return (
        f"from {module} import {name} as C\ndef f(a):\n    return C(a)\n",
        f"import {module} as m\ndef f(a):\n    return m.{name}(a)\n",
        f"import {module} as m\nC = m.{name}\ndef f(a):\n    return C(a)\n",
        f"from {module} import {name}\nC = {name}\nD = C\nx = D(1)\n",
        f"import {module} as m\nC = getattr(m, {name!r})\nx = C(1)\n",
    )


@final
class ClassReferences:
    """Every name a source file can call to reach the class called ``name``."""

    _name: str
    _tree: ast.AST
    _aliases: frozenset[str]
    __slots__ = ("_aliases", "_name", "_tree")

    def __new__(cls, source: str, name: str) -> Self:
        self = super().__new__(cls)
        self._name = name
        self._tree = ast.parse(source)
        self._aliases = self._resolved()
        return self

    @property
    def aliases(self) -> frozenset[str]:
        """The local names bound to the class, the class's own name included."""
        return self._aliases

    def constructions(self) -> int:
        """How many calls build an instance, however the class was reached."""
        return sum(
            1
            for node in ast.walk(self._tree)
            if isinstance(node, ast.Call) and self._reaches(node.func)
        )

    def method_calls(self, method: str) -> int:
        """How many calls are ``<the class, any spelling>.<method>(...)``."""
        return sum(
            1
            for node in ast.walk(self._tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == method
            and self._reaches(node.func.value)
        )

    def _reaches(self, expr: ast.expr, aliases: frozenset[str] | None = None) -> bool:
        """Whether ``expr`` evaluates to the class (or a module attribute of it)."""
        bound = self._aliases if aliases is None else aliases
        if isinstance(expr, ast.Name):
            return expr.id in bound
        if isinstance(expr, ast.Attribute):
            return expr.attr == self._name
        return (
            isinstance(expr, ast.Call)
            and isinstance(expr.func, ast.Name)
            and expr.func.id == "getattr"
            and len(expr.args) == 2
            and isinstance(expr.args[1], ast.Constant)
            and expr.args[1].value == self._name
        )

    def _resolved(self) -> frozenset[str]:
        """Grow the bound names to a fixpoint over imports and assignments."""
        bound = {self._name}
        for node in ast.walk(self._tree):
            if isinstance(node, ast.ImportFrom):
                bound.update(
                    alias.asname
                    for alias in node.names
                    if alias.name == self._name and alias.asname
                )
        grown = True
        while grown:
            grown = False
            frozen = frozenset(bound)
            for node in ast.walk(self._tree):
                if not isinstance(node, ast.Assign | ast.AnnAssign):
                    continue
                if node.value is None or not self._reaches(node.value, frozen):
                    continue
                assigned = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                for target in assigned:
                    if isinstance(target, ast.Name) and target.id not in bound:
                        bound.add(target.id)
                        grown = True
        return frozenset(bound)
