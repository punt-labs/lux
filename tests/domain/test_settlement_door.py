"""The door through which a dial is settled is structural: only the slot opens it.

A dial's ledger is taken by a ``Settler`` its reader slot hands its holder, or, past
the bound, by a ``BoundedAsk`` the slot hands a refused asker; both reach the one
capture the connection gives the slot, and nothing else reaches it. Counting calls
alone would miss a handle taken another way, so the guard counts *references*: a
name, an attribute, a string a ``getattr`` could resolve, and an import that renames
it, in every function of every module under ``src/punt_lux``, annotations and plain
imports aside. Each rule is also run over planted source to show it can fail.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Self, final

import pytest

_SRC = Path(__file__).resolve().parents[2] / "src" / "punt_lux"
_HUB = "domain/hub/"


@final
class References:
    """Where a name is referred to, by the qualified function that refers to it.

    A reference is a ``Name``, an ``Attribute``, a string constant, or an import that
    renames the name; an annotation and a plain import are not one.
    """

    _name: str
    _found: dict[str, int]
    _scope: list[str]
    __slots__ = ("_found", "_name", "_scope")

    def __new__(cls, source: str, name: str) -> Self:
        self = super().__new__(cls)
        self._name = name
        self._found = {}
        self._scope = []
        self._visit(ast.parse(source))
        return self

    @property
    def by_function(self) -> dict[str, int]:
        """The reference count of each qualified function that has any."""
        return dict(self._found)

    def _visit(self, node: ast.AST) -> None:
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            self._enter(node)
            return
        if isinstance(node, ast.Import):
            return
        if isinstance(node, ast.ImportFrom):
            if any(a.name == self._name and a.asname for a in node.names):
                self._count()
            return
        if isinstance(node, ast.AnnAssign):  # a declaration: only its value is used
            self._visit_all([node.value] if node.value else [])
            return
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id in {"__slots__", "__all__"}
            for t in node.targets
        ):
            return  # the names a class or module lists are not uses of them
        if (
            (isinstance(node, ast.Name) and node.id == self._name)
            or (isinstance(node, ast.Attribute) and node.attr == self._name)
            or (isinstance(node, ast.Constant) and node.value == self._name)
        ):
            self._count()
        self._visit_all(ast.iter_child_nodes(node))

    def _enter(
        self, node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        self._scope.append(node.name)
        if isinstance(node, ast.ClassDef):
            self._visit_all([*node.bases, *node.decorator_list, *node.body])
        else:
            # Parameter annotations and the return annotation are types, not uses.
            self._visit_all([*node.decorator_list, *node.body])
        self._scope.pop()

    def _visit_all(self, nodes: object) -> None:
        for child in nodes:  # type: ignore[attr-defined]  # an iterable of nodes
            self._visit(child)

    def _count(self) -> None:
        key = ".".join(self._scope) or "<module>"
        self._found[key] = self._found.get(key, 0) + 1


def _everywhere(name: str) -> dict[str, int]:
    """References to ``name`` across ``src/punt_lux``, keyed by file and function."""
    found: dict[str, int] = {}
    for path in sorted(_SRC.rglob("*.py")):
        rel = path.relative_to(_SRC).as_posix()
        for function, count in References(
            path.read_text("utf-8"), name
        ).by_function.items():
            found[f"{rel}:{function}"] = count
    return found


class TestTheDoorIsTheSlot:
    def test_a_settler_is_made_only_by_the_reader_slot(self) -> None:
        assert _everywhere("Settler") == {
            f"{_HUB}reader_slot.py:ReaderSlot._settler": 1
        }

    def test_a_bounded_ask_is_made_only_by_the_reader_slots_refusal(self) -> None:
        assert _everywhere("BoundedAsk") == {
            f"{_HUB}reader_slot.py:ReaderSlot.ask_settle": 1
        }

    def test_a_dial_is_marked_closed_and_shut_only_by_the_connections_capture(
        self,
    ) -> None:
        assert _everywhere("mark_closed") == {
            f"{_HUB}display_connection.py:DisplayConnection._capture": 1
        }
        assert _everywhere("shut") == {
            f"{_HUB}display_connection.py:DisplayConnection._capture": 1,
            f"{_HUB}display_connection.py:DisplayConnection._dial": 1,
        }

    def test_the_capture_reaches_only_the_slot_its_settler_and_the_bound(self) -> None:
        found = {
            where: count
            for where, count in _everywhere("_capture").items()
            if where.startswith(_HUB)
        }

        assert found == {
            f"{_HUB}bounded_ask.py:BoundedAsk.__new__": 1,
            f"{_HUB}bounded_ask.py:BoundedAsk.settle_by_bound": 1,
            f"{_HUB}display_connection.py:DisplayConnection._dial": 1,
            f"{_HUB}reader_slot.py:ReaderSlot.__new__": 1,
            f"{_HUB}reader_slot.py:ReaderSlot._settler": 1,
            f"{_HUB}reader_slot.py:ReaderSlot.ask_settle": 1,
            f"{_HUB}settler.py:Settler.__new__": 1,
            f"{_HUB}settler.py:Settler.end_stream": 1,
            f"{_HUB}settler.py:Settler.settle": 1,
        }

    @pytest.mark.parametrize("gone", ["close_if_current", "by_reader", "settle_unread"])
    def test_the_doors_the_design_removed_are_referred_to_nowhere(
        self, gone: str
    ) -> None:
        assert _everywhere(gone) == {}


class TestTheGuardCanFail:
    @pytest.mark.parametrize(
        "planted",
        [
            "def f(g):\n    return Settler(g)\n",
            "def f(g):\n    return slot_module.Settler(g)\n",
            "def f(g):\n    make = Settler\n    return make(g)\n",
            "def f(g):\n    return getattr(slot_module, 'Settler')(g)\n",
            "from punt_lux.domain.hub.settler import Settler as S\n",
            "class C:\n    def m(self, g):\n        return Settler(g)\n",
        ],
    )
    def test_every_spelling_of_a_second_door_is_counted(self, planted: str) -> None:
        assert sum(References(planted, "Settler").by_function.values()) == 1

    @pytest.mark.parametrize(
        "planted",
        [
            "from punt_lux.domain.hub.settler import Settler\n",
            "import punt_lux.domain.hub.settler\n",
            "def f(s: Settler) -> Settler:\n    return s\n",
            "class C:\n    held: Settler\n",
        ],
    )
    def test_a_type_or_a_plain_import_is_not_a_reference(self, planted: str) -> None:
        assert References(planted, "Settler").by_function == {}

    def test_references_are_keyed_by_the_qualified_function(self) -> None:
        planted = (
            "class A:\n"
            "    def m(self):\n"
            "        return Settler()\n"
            "def g():\n"
            "    return Settler() or Settler()\n"
        )

        assert References(planted, "Settler").by_function == {"A.m": 1, "g": 2}
