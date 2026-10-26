"""Every broad catch in ``src`` re-raises or is preceded by a ``ProgrammerError`` one.

A ``ProgrammerError`` marks a violated invariant of the code itself, so no boundary
that logs and carries on may swallow it. The guard walks every ``except Exception``,
``except BaseException`` and bare ``except`` in ``src/punt_lux`` and fails on the ones
that neither re-raise nor sit behind an ``except ProgrammerError: raise``.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parent.parent / "src" / "punt_lux"
_BROAD = {"Exception", "BaseException"}


def _names(node: ast.expr | None) -> set[str]:
    if node is None:
        return {"BaseException"}  # a bare ``except:``
    if isinstance(node, ast.Tuple):
        return {name for elt in node.elts for name in _names(elt)}
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Attribute):
        return {node.attr}
    return set()


def _re_raises(handler: ast.ExceptHandler) -> bool:
    return any(isinstance(n, ast.Raise) for h in handler.body for n in ast.walk(h))


def _is_programmer_error_reraise(handler: ast.ExceptHandler) -> bool:
    return (
        "ProgrammerError" in _names(handler.type)
        and len(handler.body) == 1
        and isinstance(handler.body[0], ast.Raise)
        and _raises_what_it_caught(handler, handler.body[0])
    )


def _raises_what_it_caught(handler: ast.ExceptHandler, stmt: ast.Raise) -> bool:
    """A bare ``raise``, or ``raise <name> [from ...]`` of the name it caught."""
    if stmt.exc is None:
        return True
    return isinstance(stmt.exc, ast.Name) and stmt.exc.id == handler.name


def unguarded_catches(source: str) -> list[int]:
    """Line numbers of broad catches that neither re-raise nor follow a guard."""
    found: list[int] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Try):
            continue
        guarded = False
        for handler in node.handlers:
            if _is_programmer_error_reraise(handler):
                guarded = True
            elif _names(handler.type) & _BROAD and not (guarded or _re_raises(handler)):
                found.append(handler.lineno)
    return found


class TestTheScan:
    def test_a_broad_catch_that_logs_and_carries_on_is_found(self) -> None:
        source = "try:\n    x()\nexcept Exception:\n    log()\n"

        assert unguarded_catches(source) == [3]

    def test_a_bare_except_is_found(self) -> None:
        source = "try:\n    x()\nexcept:\n    log()\n"

        assert unguarded_catches(source) == [3]

    def test_a_broad_catch_inside_a_tuple_is_found(self) -> None:
        source = "try:\n    x()\nexcept (OSError, Exception):\n    log()\n"

        assert unguarded_catches(source) == [3]

    def test_a_broad_catch_that_re_raises_is_accepted(self) -> None:
        source = "try:\n    x()\nexcept BaseException:\n    undo()\n    raise\n"

        assert unguarded_catches(source) == []

    def test_a_broad_catch_behind_a_programmer_error_re_raise_is_accepted(
        self,
    ) -> None:
        source = (
            "try:\n    x()\nexcept ProgrammerError:\n    raise\n"
            "except Exception:\n    log()\n"
        )

        assert unguarded_catches(source) == []

    def test_a_programmer_error_clause_that_does_not_re_raise_does_not_guard(
        self,
    ) -> None:
        source = (
            "try:\n    x()\nexcept ProgrammerError:\n    log()\n"
            "except Exception:\n    log()\n"
        )

        assert unguarded_catches(source) == [5]

    def test_a_guard_after_the_broad_catch_does_not_guard_it(self) -> None:
        source = (
            "try:\n    x()\nexcept Exception:\n    log()\n"
            "except ProgrammerError:\n    raise\n"
        )

        assert unguarded_catches(source) == [3]


@pytest.mark.parametrize(
    "path",
    sorted(_SRC.rglob("*.py")),
    ids=lambda p: p.relative_to(_SRC).as_posix(),
)
def test_every_broad_catch_in_src_lets_a_programmer_error_through(path: Path) -> None:
    lines = unguarded_catches(path.read_text(encoding="utf-8"))

    assert lines == [], f"{path.name}: broad catch swallows ProgrammerError at {lines}"
