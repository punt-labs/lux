"""The dial model's lock order, read from its source rather than run.

Two rules hold the request model's locks apart from the ones above and below it, and
neither can be asserted by running the code without a test that wedges when it
fails. First, the registry lock and the store lock sit above every lock of the dial
model, so no module the model reaches may name either (nor the replicator, which
calls the registry). Second, the state lock is never held while taking or waiting on
a dial's reader slot, which an inline read holds for its whole wait.

Both checks derive what they judge: the modules are the import closure of the
model's two roots, and the forbidden modules are the ones that make a reentrant lock
(the registry's and the store's). The slot rule is held by what the slot is, not by
who is seen calling it: the slot's lock is private to ``ReaderSlot`` (nothing reaches
it through another object), its one waiting entry point is the listener's claim,
nothing in ``ReaderSlot`` hands a lock out as a property, the members of the slot that
lock are derived and kept out of every state-locked step of the connection, and the
generation relays none of them (it holds no slot). Each fails on planted source, so
none can pass by checking nothing.
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


def _members(source: str, name: str) -> dict[str, ast.FunctionDef]:
    """Every method and property of the class, by name."""
    return {
        m.name: m for m in _class(source, name).body if isinstance(m, ast.FunctionDef)
    }


def _locks_the_slot(fn: ast.FunctionDef) -> bool:
    """Whether the member enters ``with self._cond`` (takes the slot's lock)."""
    return any(
        isinstance(w, ast.With)
        and any(
            isinstance(i.context_expr, ast.Attribute) and i.context_expr.attr == "_cond"
            for i in w.items
        )
        for w in ast.walk(fn)
    )


def _waits(fn: ast.FunctionDef) -> bool:
    """Whether the member waits on the slot's condition."""
    return any(
        isinstance(c, ast.Call)
        and isinstance(c.func, ast.Attribute)
        and c.func.attr in {"wait", "wait_for"}
        for c in ast.walk(fn)
    )


def _is_property(fn: ast.FunctionDef) -> bool:
    return any(
        isinstance(d, ast.Name) and d.id == "property" for d in fn.decorator_list
    )


def _reaches_through_other_objects(source: str) -> list[int]:
    """Lines that name the slot's lock on anything but ``self``.

    ``self._slot._cond`` and ``other._cond`` both reach a lock that belongs to the
    slot alone; the slot's own methods are the only code that may name it.
    """
    return [
        n.lineno
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Attribute)
        and n.attr == "_cond"
        and not (isinstance(n.value, ast.Name) and n.value.id == "self")
    ]


@final
class SlotTakers:
    """The ``ReaderSlot`` members that take or wait on its lock."""

    _members: frozenset[str]
    __slots__ = ("_members",)

    def __new__(cls, slot_source: str) -> Self:
        self = super().__new__(cls)
        slot = _members(slot_source, "ReaderSlot")
        self._members = frozenset(
            name for name, m in slot.items() if _locks_the_slot(m)
        )
        return self

    @property
    def names(self) -> frozenset[str]:
        """The slot members that take or wait on its lock."""
        return self._members

    def relayed_by(self, dial_source: str) -> list[str]:
        """The ``DialGeneration`` members that name a locking slot member."""
        return sorted(
            name
            for name, m in _members(dial_source, "DialGeneration").items()
            if any(
                isinstance(n, ast.Attribute) and n.attr in self._members
                for n in ast.walk(m)
            )
        )

    def under_the_state_lock(self, connection_source: str) -> list[str]:
        """What ``DisplayConnection`` does under its state lock to the slot.

        A call, or a property read, of a member that takes the slot's lock. Handing
        the slot out, or reading a flag that takes nothing, is allowed.
        """
        found: list[str] = []
        cls = _class(connection_source, "DisplayConnection")
        for method in cls.body:
            if not isinstance(method, ast.FunctionDef):
                continue
            for block in ast.walk(method):
                if not (isinstance(block, ast.With) and self._holds_state_lock(block)):
                    continue
                touched = {
                    n.attr
                    for n in ast.walk(block)
                    if isinstance(n, ast.Attribute) and n.attr in self._members
                }
                found += [f"{method.name}: {attr}" for attr in sorted(touched)]
        return found

    @staticmethod
    def _holds_state_lock(block: ast.With) -> bool:
        return any(
            isinstance(i.context_expr, ast.Attribute)
            and i.context_expr.attr == "_state_lock"
            for i in block.items
        )


def _hub(name: str) -> str:
    return (_SRC / "punt_lux" / "domain" / "hub" / name).read_text(encoding="utf-8")


def _takers() -> SlotTakers:
    return SlotTakers(_hub("reader_slot.py"))


def _hub_sources() -> dict[str, str]:
    return {
        path.name: path.read_text(encoding="utf-8")
        for path in (_SRC / "punt_lux" / "domain" / "hub").rglob("*.py")
    }


_PLANTED_SLOT = (
    "class ReaderSlot:\n"
    "    def __new__(cls):\n"
    "        self = object.__new__(cls)\n"
    "        self._cond = None\n"
    "        return self\n"
    "    @property\n"
    "    def has_listener(self):\n"
    "        return self._holder == 'listener'\n"
    "    def claim_for_listener(self):\n"
    "        with self._cond:\n"
    "            self._cond.wait_for(lambda: True)\n"
    "    def release_listener(self):\n"
    "        with self._cond:\n"
    "            pass\n"
)
_PLANTED_DIAL = (
    "class DialGeneration:\n"
    "    def claim_reader(self):\n"
    "        return self._slot.claim_for_listener()\n"
    "    def release_reader(self):\n"
    "        self._slot.release_listener()\n"
)


class TestTheSlotsLockIsPrivateAndItsWaitIsOne:
    def test_nothing_reaches_the_slots_lock_through_another_object(self) -> None:
        reaching = {
            name: lines
            for name, source in _hub_sources().items()
            if (lines := _reaches_through_other_objects(source))
        }

        assert reaching == {}

    def test_the_one_waiting_member_is_the_listeners_claim(self) -> None:
        slot = _members(_hub("reader_slot.py"), "ReaderSlot")

        assert {name for name, m in slot.items() if _waits(m)} == {"claim_for_listener"}

    def test_no_property_of_the_slot_takes_its_lock(self) -> None:
        slot = _members(_hub("reader_slot.py"), "ReaderSlot")

        assert [
            name for name, m in slot.items() if _is_property(m) and _locks_the_slot(m)
        ] == []

    def test_a_dial_that_names_the_slots_lock_is_found(self) -> None:
        planted = (
            "class DialGeneration:\n"
            "    @property\n"
            "    def has_reader(self):\n"
            "        with self._slot._cond:\n"
            "            return True\n"
        )

        assert _reaches_through_other_objects(planted) == [4]

    def test_the_slots_own_methods_may_name_its_lock(self) -> None:
        assert _reaches_through_other_objects(_PLANTED_SLOT) == []

    def test_a_second_waiting_member_is_found(self) -> None:
        planted = _PLANTED_SLOT + (
            "    def inline(self):\n"
            "        with self._cond:\n"
            "            self._cond.wait(1)\n"
        )

        slot = _members(planted, "ReaderSlot")

        assert {name for name, m in slot.items() if _waits(m)} == {
            "claim_for_listener",
            "inline",
        }

    def test_a_property_that_gains_the_lock_is_found(self) -> None:
        planted = _PLANTED_SLOT.replace(
            "        return self._holder == 'listener'",
            "        with self._cond:\n            return self._holder == 'listener'",
        )

        slot = _members(planted, "ReaderSlot")

        assert [
            name for name, m in slot.items() if _is_property(m) and _locks_the_slot(m)
        ] == ["has_listener"]


class TestTheStateLockNeverTakesOrWaitsOnTheReaderSlot:
    def test_the_slot_takers_are_derived_from_the_slot(self) -> None:
        assert _takers().names == {
            "claim_for_listener",
            "release_listener",
            "inline",
        }

    def test_no_state_lock_step_takes_or_waits_on_the_slot(self) -> None:
        assert _takers().under_the_state_lock(_hub("display_connection.py")) == []

    def test_the_generation_relays_no_slot_call(self) -> None:
        assert _takers().relayed_by(_hub("dial_generation.py")) == []

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
            "            self._reading.claim_for_listener()\n"
        )

        assert _takers().under_the_state_lock(planted) == ["open: claim_for_listener"]

    def test_an_inline_read_under_the_state_lock_is_found(self) -> None:
        planted = (
            "class DisplayConnection:\n"
            "    def require(self):\n"
            "        with self._state_lock:\n"
            "            with self._reading.inline():\n"
            "                pass\n"
        )

        assert _takers().under_the_state_lock(planted) == ["require: inline"]

    def test_handing_the_slot_out_and_reading_who_holds_it_are_allowed(self) -> None:
        planted = (
            "class DisplayConnection:\n"
            "    def has_reader(self):\n"
            "        with self._state_lock:\n"
            "            return self._reading.has_listener\n"
            "    def reading(self, generation):\n"
            "        with self._state_lock:\n"
            "            return self._reading\n"
        )

        assert _takers().under_the_state_lock(planted) == []

    def test_a_slot_property_that_gains_the_lock_is_found_under_the_state_lock(
        self,
    ) -> None:
        # The slot's has_listener takes the lock; the connection reads it as a
        # property under the state lock: an edge no call-spotting sees.
        slot = _PLANTED_SLOT.replace(
            "        return self._holder == 'listener'",
            "        with self._cond:\n            return self._holder == 'listener'",
        )
        takers = SlotTakers(slot)
        connection = (
            "class DisplayConnection:\n"
            "    def has_reader(self):\n"
            "        with self._state_lock:\n"
            "            return self._reading.has_listener\n"
        )

        assert "has_listener" in takers.names
        assert takers.under_the_state_lock(connection) == ["has_reader: has_listener"]

    def test_a_relay_on_the_generation_is_found(self) -> None:
        takers = SlotTakers(_PLANTED_SLOT)

        assert takers.relayed_by(_PLANTED_DIAL) == ["claim_reader", "release_reader"]
