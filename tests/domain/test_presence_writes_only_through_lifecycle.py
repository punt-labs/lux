"""Presence is written only through ``ClientLifecycle``: a structural guard.

A write to a session's record, lease, listener slot or callbacks changes who the
Clients menu lists, so it owes the Hub a mark and a bound sink, paid under the
store lock. Only ``ClientLifecycle`` pays that. The registry therefore hands its
write surface (``PresenceWrites``) away exactly once, to the lifecycle, and nothing
else may reach it or the registry's session state.

The guard reads the source as syntax. A module reaches the surface by an import
that resolves to the writes' module (absolute, relative, aliased, or of the module
rather than the name), by taking it from the registry, or by holding the
lifecycle's own handle on it; the registry's session state is written only by the
writes. The roster's renumbering is held by what exists, not by who is seen calling
it: the write is the one method of ``RosterRelease``, built once, handed away once to
the writes, and what readers are given can only name. The lifecycle
uses its handle on the writes only as the receiver of a call, never handing it on.
Each rule is exercised on planted source to prove it can fail.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from punt_lux.domain.hub.hub_clients import HubClientRegistry
from tests.source_imports import module_name, resolved_imports

_ROOT = Path(__file__).resolve().parents[2]
_SRC = _ROOT / "src"
_TESTS = _ROOT / "tests"
_WRITES_MODULE = "punt_lux.domain.hub.presence_writes"
_WRITES_FILE = _SRC / "punt_lux" / "domain" / "hub" / "presence_writes.py"

# Every public method of ``PresenceWrites`` writes: the surface has no reads.
_EXPECTED_WRITES = {
    "record",
    "renew_if_registered",
    "discard",
    "reap_lapsed",
    "attach",
    "detach",
    "register_callback",
}
_EXPECTED_READS: set[str] = set()

_DICT_MUTATORS = {
    "pop",
    "popitem",
    "clear",
    "update",
    "setdefault",
    "__setitem__",
    "__delitem__",
}
_SESSION_STATE = "_sessions"
_ROSTER_STATE = "_roster"
_ROSTER_FILE = _SRC / "punt_lux" / "domain" / "hub" / "client_roster.py"
_ROSTER_REL = "src/punt_lux/domain/hub/client_roster.py"
_NAMED_SESSIONS_REL = "src/punt_lux/domain/hub/named_sessions.py"
# What the roster itself offers: to name connections, to read the names held, and to
# hand its release away. The release is the one place a survivor is renumbered.
_ROSTER_OWN = {"names_for", "held", "take_release"}
# The roster's one write, private to it: the release is the only way to ask for it.
_ROSTER_DROP = "_release_departed"
# Who may name the release: its home and the writes that hold it.
_RELEASE_NAMERS = {_ROSTER_REL, "src/punt_lux/domain/hub/presence_writes.py"}

# The registry hands the surface out and the lifecycle takes it.
_IMPORTERS = {
    "src/punt_lux/domain/hub/hub_clients.py",
    "src/punt_lux/domain/hub/client_lifecycle.py",
}
_LIFECYCLE = "src/punt_lux/domain/hub/client_lifecycle.py"
# The unit tests of the writes and of the lock order take a registry's writes on
# their own, and this file plants violations to prove its own rules.
_WRITE_UNIT_TESTS = {
    "tests/domain/test_hub_clients.py",
    "tests/domain/test_client_lifecycle_lock_order.py",
}
_THIS_FILE = "tests/domain/test_presence_writes_only_through_lifecycle.py"
# The registry builds its own empty session map; nothing else outside the writes
# may change it.
_MAY_INITIALISE = ("src/punt_lux/domain/hub/hub_clients.py", "__new__")
_WRITES_FILE_REL = "src/punt_lux/domain/hub/presence_writes.py"
_REGISTRY_FILE = _MAY_INITIALISE[0]


def _reaches_the_writes(source: str, module: str) -> bool:
    """Whether ``source`` (importable as ``module``) imports or names the writes."""
    tree = ast.parse(source)
    if _WRITES_MODULE in resolved_imports(source, module):
        return True
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "PresenceWrites":
            return True
        if isinstance(node, ast.Constant) and node.value == _WRITES_MODULE:
            return True
    return False


def _calls_attribute(source: str, attribute: str) -> bool:
    """Whether ``source`` calls ``<expr>.<attribute>(...)``."""
    return any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == attribute
        for node in ast.walk(ast.parse(source))
    )


def _reads_attribute(source: str, attribute: str) -> bool:
    """Whether ``source`` reads ``<expr>.<attribute>`` at all."""
    return any(
        isinstance(node, ast.Attribute) and node.attr == attribute
        for node in ast.walk(ast.parse(source))
    )


def _label(node: ast.expr) -> str | None:
    """The trailing name of a ``name`` or ``expr.name`` expression."""
    if isinstance(node, ast.Attribute):
        return node.attr
    return node.id if isinstance(node, ast.Name) else None


def _receiver(node: ast.expr) -> str:
    """``self`` for ``self.<state>``, ``other`` for state reached through another."""
    owner = node.value if isinstance(node, ast.Attribute) else None
    return "self" if isinstance(owner, ast.Name) and owner.id == "self" else "other"


class _StateWrites(ast.NodeVisitor):
    """The places that change a ``_sessions`` map, with their method and receiver.

    The receiver is ``self`` (the class's own map) or ``other`` (a map reached
    through another object, which is how the registry's would be written from
    outside). A write is a subscript store or delete on the state, a rebinding of
    it, or any mutating dict method named on it -- called or merely referenced, since
    ``map(self._sessions.pop, ...)`` writes without a call on the attribute.
    """

    def __init__(self) -> None:
        self.found: list[tuple[str, int, str]] = []
        self._scope: list[str] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scope.append(node.name)
        self.generic_visit(node)
        self._scope.pop()

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if (
            isinstance(node.ctx, ast.Store | ast.Del)
            and _label(node.value) == _SESSION_STATE
        ):
            self._record(node, node.value)
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if isinstance(node.ctx, ast.Store) and node.attr == _SESSION_STATE:
            self._record(node, node)
        if node.attr in _DICT_MUTATORS and _label(node.value) == _SESSION_STATE:
            self._record(node, node.value)
        self.generic_visit(node)

    def _record(self, node: ast.AST, state: ast.expr) -> None:
        method = self._scope[-1] if self._scope else "<module>"
        self.found.append((method, node.lineno, _receiver(state)))  # type: ignore[attr-defined]


def _state_writes(source: str) -> list[tuple[str, int, str]]:
    visitor = _StateWrites()
    visitor.visit(ast.parse(source))
    return visitor.found


def _roster_methods(source: str, name: str = "ClientRoster") -> set[str]:
    """The public methods of a roster class, read from its class body."""
    tree = ast.parse(source)
    cls = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == name
    )
    return {
        m.name
        for m in cls.body
        if isinstance(m, ast.FunctionDef) and not m.name.startswith("_")
    }


def _drops_names(node: ast.AST) -> bool:
    """Whether ``node`` drops a name from the roster's holdings.

    Dropping is ``self._names.drop(...)`` or popping a connection out of ``_key_of``:
    the two steps that make a survivor's label move.
    """
    return any(
        isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and (
            (call.func.attr == "drop" and _label(call.func.value) == "_names")
            or (call.func.attr == "pop" and _label(call.func.value) == "_key_of")
        )
        for call in ast.walk(node)
    )


def _classes_that_drop_names(source: str) -> set[str]:
    """The classes whose methods drop a name from the roster's holdings."""
    return {
        cls.name
        for cls in ast.walk(ast.parse(source))
        if isinstance(cls, ast.ClassDef) and _drops_names(cls)
    }


def _methods_that_drop_names(source: str, name: str) -> set[str]:
    """The methods of class ``name`` that drop a name from the roster's holdings."""
    cls = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ClassDef) and node.name == name
    )
    return {
        m.name for m in cls.body if isinstance(m, ast.FunctionDef) and _drops_names(m)
    }


def _methods_that_name(source: str, cls_name: str, attribute: str) -> set[str]:
    """The methods of class ``cls_name`` that read ``<expr>.<attribute>``."""
    cls = next(
        node
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ClassDef) and node.name == cls_name
    )
    return {
        m.name
        for m in cls.body
        if isinstance(m, ast.FunctionDef)
        and any(
            isinstance(n, ast.Attribute) and n.attr == attribute for n in ast.walk(m)
        )
    }


def _constructions_of(source: str, name: str) -> int:
    return sum(
        1
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == name
    )


def _names_in(source: str) -> set[str]:
    """Every name the source uses, imports or reads off an object."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.ImportFrom | ast.Import):
            found.update(alias.name.split(".")[-1] for alias in node.names)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
    return found


def _handed_on_handles(source: str) -> list[int]:
    """The lines where ``._writes`` is used other than as the receiver of a call."""
    tree = ast.parse(source)
    receivers = {
        id(call.func.value)
        for call in ast.walk(tree)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Attribute)
    }
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and node.attr == "_writes"
        and not isinstance(node.ctx, ast.Store)
        and id(node) not in receivers
    ]


def _derived_writes() -> tuple[set[str], set[str]]:
    """The public methods of ``PresenceWrites`` that write, and those that only read."""
    tree = ast.parse(_WRITES_FILE.read_text())
    cls = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "PresenceWrites"
    )
    writes: set[str] = set()
    reads: set[str] = set()
    for method in cls.body:
        if not isinstance(method, ast.FunctionDef) or method.name.startswith("_"):
            continue
        source = ast.unparse(method)
        roster = any(
            isinstance(node, ast.Attribute) and _label(node.value) == _ROSTER_STATE
            for node in ast.walk(method)
        )
        (writes if roster or _state_writes(source) else reads).add(method.name)
    return writes, reads


def _files(root: Path, pattern: str = "*.py") -> list[tuple[str, str]]:
    return [
        (path.relative_to(_ROOT).as_posix(), path.read_text())
        for path in sorted(root.rglob(pattern))
    ]


def _importers(root: Path) -> set[str]:
    return {
        rel
        for rel, text in _files(root)
        if rel != _WRITES_FILE_REL and _reaches_the_writes(text, module_name(rel))
    }


def _callers(root: Path, attribute: str) -> set[str]:
    return {rel for rel, text in _files(root) if _calls_attribute(text, attribute)}


def _readers(root: Path, attribute: str) -> set[str]:
    return {rel for rel, text in _files(root) if _reads_attribute(text, attribute)}


def _outside_state_writers(root: Path) -> set[tuple[str, str]]:
    """Every (file, method) that changes the registry's session map but the writes.

    Other classes keep maps of their own under the same name, so a file's own
    ``self`` map counts only in the registry's module; anywhere else a write counts
    when it reaches a map through another object.
    """
    return {
        (rel, method)
        for rel, text in _files(root)
        if rel != _WRITES_FILE_REL
        for method, _, receiver in _state_writes(text)
        if receiver == "other" or rel == _REGISTRY_FILE
    } - {_MAY_INITIALISE}


def test_the_roster_itself_only_names_and_hands_its_release_away() -> None:
    assert _roster_methods(_ROSTER_FILE.read_text()) == _ROSTER_OWN


def test_only_the_roster_drops_a_name_and_in_one_private_method() -> None:
    source = _ROSTER_FILE.read_text()

    assert _classes_that_drop_names(source) == {"ClientRoster"}
    assert _methods_that_drop_names(source, "ClientRoster") == {_ROSTER_DROP}


def test_the_roster_s_drop_is_reached_only_through_the_release_it_hands_away() -> None:
    readers = {
        rel for rel, text in _files(_SRC) if _reads_attribute(text, _ROSTER_DROP)
    }

    assert readers == {_ROSTER_REL}
    assert _methods_that_name(
        _ROSTER_FILE.read_text(), "ClientRoster", _ROSTER_DROP
    ) == {"take_release"}


def test_the_release_is_built_once_by_the_roster_that_hands_it_away() -> None:
    built = {
        rel: count
        for rel, text in _files(_SRC)
        if (count := _constructions_of(text, "RosterRelease"))
    }

    assert built == {_ROSTER_REL: 1}


def test_the_roster_s_release_is_taken_once_in_the_source() -> None:
    callers = {
        rel for rel, text in _files(_SRC) if _calls_attribute(text, "take_release")
    }

    assert callers == {_REGISTRY_FILE}


def test_only_the_roster_and_the_writes_name_the_release() -> None:
    namers = {rel for rel, text in _files(_SRC) if "RosterRelease" in _names_in(text)}

    assert namers == _RELEASE_NAMERS


def test_readers_of_the_roster_are_given_only_what_names() -> None:
    named_sessions = (_ROOT / _NAMED_SESSIONS_REL).read_text()

    assert "RosterNames" in _names_in(named_sessions)
    assert "ClientRoster" not in _names_in(named_sessions)


def test_the_lifecycle_only_calls_through_its_handle_on_the_writes() -> None:
    lifecycle = (_ROOT / _LIFECYCLE).read_text()

    assert _handed_on_handles(lifecycle) == []


def test_the_write_set_is_exactly_the_writes_public_methods() -> None:
    assert _derived_writes() == (_EXPECTED_WRITES, _EXPECTED_READS)


def test_only_the_registry_and_the_lifecycle_reach_the_writes_in_the_source() -> None:
    assert _importers(_SRC) == _IMPORTERS


def test_only_the_lifecycle_takes_the_writes_in_the_source() -> None:
    assert _callers(_SRC, "take_writes") == {_LIFECYCLE}


def test_only_the_lifecycle_holds_the_writes_handle_in_the_source() -> None:
    assert _readers(_SRC, "_writes") == {_LIFECYCLE}


def test_nothing_but_the_writes_changes_the_registrys_session_state() -> None:
    assert _outside_state_writers(_SRC) == set()


def test_no_test_outside_the_write_unit_tests_reaches_the_writes() -> None:
    allowed = _WRITE_UNIT_TESTS | {_THIS_FILE}

    assert _importers(_TESTS) - allowed == set()
    assert _callers(_TESTS, "take_writes") - allowed == set()
    assert _readers(_TESTS, "_writes") - allowed == set()


def test_the_registry_has_no_write_of_its_own() -> None:
    own = {name for name in vars(HubClientRegistry) if not name.startswith("_")}

    assert own.isdisjoint(_EXPECTED_WRITES)


def test_the_registry_gives_its_writes_away_exactly_once() -> None:
    registry = HubClientRegistry()
    registry.take_writes()

    with pytest.raises(ValueError, match="already handed"):
        registry.take_writes()


class TestTheRulesCanFail:
    """Each rule above, run on source that breaks it."""

    @pytest.mark.parametrize(
        ("source", "module"),
        [
            (
                "from punt_lux.domain.hub.presence_writes import PresenceWrites",
                "punt_lux.x",
            ),
            ("from punt_lux.domain.hub import presence_writes", "punt_lux.x"),
            (
                "from punt_lux.domain.hub import presence_writes as pw",
                "punt_lux.x",
            ),
            ("import punt_lux.domain.hub.presence_writes as pw", "punt_lux.x"),
            ("from .presence_writes import PresenceWrites", "punt_lux.domain.hub.x"),
            ("from . import presence_writes", "punt_lux.domain.hub.x"),
            ("from ..hub import presence_writes", "punt_lux.domain.hub.x"),
            ("import punt_lux.domain.hub as h\nh.presence_writes.PresenceWrites", "a"),
            (
                "import importlib\nimportlib.import_module("
                + repr(_WRITES_MODULE)
                + ")",
                "a",
            ),
        ],
    )
    def test_an_import_of_the_writes_in_any_spelling_is_reached(
        self, source: str, module: str
    ) -> None:
        assert _reaches_the_writes(source, module)

    @pytest.mark.parametrize(
        ("source", "module"),
        [
            ("from punt_lux.domain.hub import hub_clients", "punt_lux.x"),
            ("from .hub_clients import HubClientRegistry", "punt_lux.domain.hub.x"),
            ("from .presence_writes import PresenceWrites", "punt_lux.other.x"),
        ],
    )
    def test_an_import_of_something_else_is_not_reached(
        self, source: str, module: str
    ) -> None:
        assert not _reaches_the_writes(source, module)

    @pytest.mark.parametrize(
        "body",
        [
            "self._sessions[cid] = session",
            "del self._sessions[cid]",
            "self._sessions.pop(cid)",
            "self._sessions.clear()",
            "self._sessions.update(other)",
            "deque(map(self._sessions.pop, lapsed), maxlen=0)",
            "self._sessions = {}",
            "registry._sessions[cid] = session",
        ],
    )
    def test_a_new_method_that_changes_session_state_is_found(self, body: str) -> None:
        source = f"class R:\n    def evict(self, cid):\n        {body}\n"

        assert [(m, n) for m, n, _ in _state_writes(source)] == [("evict", 3)]

    def test_a_write_through_another_object_is_marked_as_such(self) -> None:
        source = "def f(registry, cid, s):\n    registry._sessions[cid] = s\n"

        assert _state_writes(source) == [("f", 2, "other")]

    def test_a_method_that_only_reads_session_state_is_not_a_write(self) -> None:
        source = (
            "class R:\n"
            "    def peek(self, cid):\n"
            "        return self._sessions.get(cid), dict(self._sessions)\n"
        )

        assert _state_writes(source) == []

    def test_a_planted_public_write_enters_the_derived_write_set(self) -> None:
        # The derivation is the scan of a class body, so a method added to the
        # writes that mutates state is a write without anyone editing a list.
        source = (
            "class PresenceWrites:\n"
            "    def peek(self, cid):\n"
            "        return self._sessions.get(cid)\n"
            "    def evict(self, cid):\n"
            "        self._sessions.pop(cid)\n"
        )
        tree = ast.parse(source)
        methods = {
            m.name: bool(_state_writes(ast.unparse(m)))
            for m in tree.body[0].body  # type: ignore[attr-defined]
        }

        assert methods == {"peek": False, "evict": True}

    def test_taking_the_writes_through_another_module_is_found(self) -> None:
        assert _calls_attribute("registry.take_writes()", "take_writes")
        assert _reads_attribute("self.lifecycle._writes.record(c)", "_writes")

    @pytest.mark.parametrize(
        "body",
        [
            "Helper(self._writes)",
            "handle = self._writes",
            "return self._writes",
            "register(callback=self._writes)",
        ],
    )
    def test_handing_the_writes_handle_on_is_found(self, body: str) -> None:
        source = f"class C:\n    def f(self):\n        {body}\n"

        assert _handed_on_handles(source) == [3]

    def test_calling_through_the_handle_and_storing_it_are_not_handing_on(self) -> None:
        source = (
            "class C:\n"
            "    def __new__(cls, writes):\n"
            "        self = super().__new__(cls)\n"
            "        self._writes = writes\n"
            "        return self\n"
            "    def f(self, c):\n"
            "        return self._writes.record(c)\n"
        )

        assert _handed_on_handles(source) == []

    def test_a_method_that_drops_a_name_outside_the_release_is_found(self) -> None:
        source = (
            "class ClientRoster:\n"
            "    def evict(self, cid):\n"
            "        self._key_of.pop(cid)\n"
            "class RosterRelease:\n"
            "    def release(self, cid):\n"
            "        self._names.drop(cid)\n"
        )

        assert _classes_that_drop_names(source) == {"ClientRoster", "RosterRelease"}
        assert _methods_that_drop_names(source, "ClientRoster") == {"evict"}

    def test_a_planted_roster_method_enters_the_derived_set(self) -> None:
        source = (
            "class ClientRoster:\n"
            "    def names_for(self, ids):\n"
            "        return {}\n"
            "    def release(self, departed):\n"
            "        return frozenset()\n"
        )

        assert _roster_methods(source) == {"names_for", "release"}

    def test_a_second_construction_of_the_release_is_counted(self) -> None:
        source = "def f(roster):\n    return RosterRelease(roster._release_departed)\n"

        assert _constructions_of(source, "RosterRelease") == 1

    def test_a_module_that_names_the_release_in_any_spelling_is_found(self) -> None:
        for source in (
            "from punt_lux.domain.hub.client_roster import RosterRelease\n",
            "import punt_lux.domain.hub.client_roster as r\nx = r.RosterRelease\n",
            "def f(release: RosterRelease) -> None:\n    release.release(())\n",
        ):
            assert "RosterRelease" in _names_in(source), source
