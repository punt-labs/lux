"""The dial model's lock order, read from its source rather than run.

Two rules hold the request model's locks apart from the ones above and below it, and
neither can be asserted by running the code without a test that wedges when it
fails. First, the registry lock and the store lock sit above every lock of the dial
model, so no module the model reaches may name either (nor the replicator, which
calls the registry). Second, the state lock is never held while taking or waiting on
a dial's reader slot, which an inline read holds for its whole wait.

Both checks derive what they judge: the modules are the import closure of the
model's two roots, the forbidden modules are the ones that make a reentrant lock (the
registry's and the store's), and the slot-taking members are the
``DialGeneration`` methods that reach a locking ``ReaderSlot`` method. Each fails on
planted source, so none can pass by checking nothing.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Self, final

from tests.source_imports import import_closure, modules_calling

_SRC = Path(__file__).resolve().parents[2] / "src"
_HUB = "punt_lux.domain.hub"
_ROOTS = (f"{_HUB}.display_requests", f"{_HUB}.display_listener")
# What sits above the model's locks: the registry (its RLock), the store (its lock),
# the store itself, and the replicator that calls the registry; and the singletons
# a module would reach them through.
_REENTRANT = "RLock"


def _forbidden(src: Path, within: str = _HUB) -> frozenset[str]:
    """The modules whose lock sits above the model's: those that make a reentrant one.

    The model's own locks are plain; the registry and the store each take theirs
    reentrantly because a nested caller re-enters, and everything the model's
    callers hold across it is built on those two.
    """
    return modules_calling(src, within=within, attr=_REENTRANT)


def _reaches_the_forbidden(
    src: Path,
    roots: tuple[str, ...],
    forbidden: frozenset[str],
    within: str = _HUB,
) -> list[str]:
    graph = import_closure(src, roots, within=within)
    return [
        f"{module} imports {dep}"
        for module, deps in sorted(graph.items())
        for dep in sorted(deps & forbidden)
    ]


class TestNoModuleOfTheDialModelNamesWhatSitsAboveItsLocks:
    def test_the_modules_the_model_reaches_are_derived_from_its_roots(self) -> None:
        graph = import_closure(_SRC, _ROOTS, within=_HUB)

        assert set(_ROOTS) <= graph.keys()
        assert {f"{_HUB}.dial_generation", f"{_HUB}.reply_sink"} <= graph.keys()
        assert {f"{_HUB}.inbound_router", f"{_HUB}.reader_slot"} <= graph.keys()

    def test_what_sits_above_is_found_by_the_reentrant_locks_it_makes(self) -> None:
        forbidden = _forbidden(_SRC)

        assert {f"{_HUB}.clients", f"{_HUB}.store_lock"} <= forbidden
        assert f"{_HUB}.dial_generation" not in forbidden

    def test_no_module_the_model_reaches_imports_one_of_them(self) -> None:
        assert _reaches_the_forbidden(_SRC, _ROOTS, _forbidden(_SRC)) == []

    def test_the_check_fails_when_a_module_a_leaf_imports_names_the_registry(
        self, tmp_path: Path
    ) -> None:
        hub = tmp_path / "pkg" / "hub"
        hub.mkdir(parents=True)
        (tmp_path / "pkg" / "__init__.py").write_text("")
        (hub / "__init__.py").write_text("")
        (hub / "root.py").write_text("from pkg.hub import leaf\n")
        (hub / "leaf.py").write_text("from pkg.hub.registry import Registry\n")
        (hub / "registry.py").write_text(
            "import threading\nclass Registry:\n    lock = threading.RLock()\n"
        )
        forbidden = _forbidden(tmp_path, "pkg.hub")

        found = _reaches_the_forbidden(
            tmp_path, ("pkg.hub.root",), forbidden, within="pkg.hub"
        )

        assert found == ["pkg.hub.leaf imports pkg.hub.registry"]

    def test_the_check_passes_a_closure_that_never_reaches_them(
        self, tmp_path: Path
    ) -> None:
        hub = tmp_path / "pkg" / "hub"
        hub.mkdir(parents=True)
        (tmp_path / "pkg" / "__init__.py").write_text("")
        (hub / "__init__.py").write_text("")
        (hub / "root.py").write_text("from pkg.hub import leaf\n")
        (hub / "leaf.py").write_text("X = 1\n")
        (hub / "registry.py").write_text(
            "import threading\nclass Registry:\n    lock = threading.RLock()\n"
        )
        forbidden = _forbidden(tmp_path, "pkg.hub")

        assert (
            _reaches_the_forbidden(
                tmp_path, ("pkg.hub.root",), forbidden, within="pkg.hub"
            )
            == []
        )


def _class(source: str, name: str) -> ast.ClassDef:
    return next(
        n
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.ClassDef) and n.name == name
    )


def _called(node: ast.AST) -> set[str]:
    return {
        n.func.attr
        for n in ast.walk(node)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }


@final
class SlotTakers:
    """The ``DialGeneration`` members that take or wait on the reader slot."""

    _members: frozenset[str]
    __slots__ = ("_members",)

    def __new__(cls, dial_source: str, slot_source: str) -> Self:
        self = super().__new__(cls)
        # A ReaderSlot method locks when its body enters ``with self._cond``.
        slot = _class(slot_source, "ReaderSlot")
        locking = {
            m.name
            for m in slot.body
            if isinstance(m, ast.FunctionDef)
            and any(
                isinstance(w, ast.With)
                and any(
                    isinstance(i.context_expr, ast.Attribute)
                    and i.context_expr.attr == "_cond"
                    for i in w.items
                )
                for w in ast.walk(m)
            )
        }
        dial = _class(dial_source, "DialGeneration")
        self._members = frozenset(
            m.name
            for m in dial.body
            if isinstance(m, ast.FunctionDef) and _called(m) & locking
        )
        return self

    @property
    def names(self) -> frozenset[str]:
        """The members that take or wait on the slot."""
        return self._members

    def under_the_state_lock(self, connection_source: str) -> list[str]:
        """What ``DisplayConnection`` does under its state lock to the slot."""
        found: list[str] = []
        cls = _class(connection_source, "DisplayConnection")
        for method in cls.body:
            if not isinstance(method, ast.FunctionDef):
                continue
            for block in ast.walk(method):
                if not (isinstance(block, ast.With) and self._holds_state_lock(block)):
                    continue
                found += [
                    f"{method.name}: {attr}"
                    for attr in sorted(
                        (_called(block) & self._members) | self._slot_refs(block)
                    )
                ]
        return found

    @staticmethod
    def _holds_state_lock(block: ast.With) -> bool:
        return any(
            isinstance(i.context_expr, ast.Attribute)
            and i.context_expr.attr == "_state_lock"
            for i in block.items
        )

    @staticmethod
    def _slot_refs(block: ast.With) -> set[str]:
        return {
            n.attr
            for n in ast.walk(block)
            if isinstance(n, ast.Attribute) and n.attr == "_slot"
        }


def _hub(name: str) -> str:
    return (_SRC / "punt_lux" / "domain" / "hub" / name).read_text(encoding="utf-8")


def _takers() -> SlotTakers:
    return SlotTakers(_hub("dial_generation.py"), _hub("reader_slot.py"))


class TestTheStateLockNeverTakesOrWaitsOnTheReaderSlot:
    def test_the_slot_takers_are_derived_from_the_two_classes(self) -> None:
        assert _takers().names == {
            "claim_reader",
            "release_reader",
            "inline_reading",
        }

    def test_no_state_lock_step_takes_or_waits_on_the_slot(self) -> None:
        assert _takers().under_the_state_lock(_hub("display_connection.py")) == []

    def test_the_guard_covers_every_state_lock_step_not_three_it_was_given(
        self,
    ) -> None:
        # The state-locked steps are scanned from the class: more than the three
        # the runtime test drives, so a step added later is judged too.
        connection = _class(_hub("display_connection.py"), "DisplayConnection")
        locked = [
            m.name
            for m in connection.body
            if isinstance(m, ast.FunctionDef)
            and any(
                isinstance(w, ast.With) and _takers()._holds_state_lock(w)
                for w in ast.walk(m)
            )
        ]

        assert len(locked) > 3

    def test_a_claim_under_the_state_lock_is_found(self) -> None:
        planted = (
            "class DisplayConnection:\n"
            "    def open(self):\n"
            "        with self._state_lock:\n"
            "            self._current.claim_reader()\n"
        )

        assert _takers().under_the_state_lock(planted) == ["open: claim_reader"]

    def test_an_inline_read_under_the_state_lock_is_found(self) -> None:
        planted = (
            "class DisplayConnection:\n"
            "    def require(self):\n"
            "        with self._state_lock:\n"
            "            with self._current.inline_reading():\n"
            "                pass\n"
        )

        assert _takers().under_the_state_lock(planted) == ["require: inline_reading"]

    def test_taking_the_slot_directly_under_the_state_lock_is_found(self) -> None:
        planted = (
            "class DisplayConnection:\n"
            "    def close(self):\n"
            "        with self._state_lock:\n"
            "            with self._current._slot:\n"
            "                pass\n"
        )

        assert _takers().under_the_state_lock(planted) == ["close: _slot"]

    def test_reading_who_holds_the_slot_is_allowed_under_the_state_lock(self) -> None:
        planted = (
            "class DisplayConnection:\n"
            "    def has_reader(self):\n"
            "        with self._state_lock:\n"
            "            return self._current.has_reader\n"
        )

        assert _takers().under_the_state_lock(planted) == []
