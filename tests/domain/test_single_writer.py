"""The replicator is the only Hub-side writer to the display connection.

No MCP mutation tool, click dispatch, or Hub-hosted app may send to the display:
they write ``HubDisplay`` and mark a scene dirty, and the one background replicator
does every send. This guard reads the source of every module and fails if a display
write appears outside the modules that own the send path, so the single-writer
invariant cannot regress silently.

The write verbs are derived from the sources that define them, not listed: a public
``DisplayRequests`` method is a write when its body (through the private helpers it
calls) reaches a ``DialGeneration`` write, and a ``DialGeneration`` ``send*`` method
is a write unless it registers a reply to wait for (a ping or a query). A call is the
display's when its receiver is reached through ``.requests``, ``.dial`` or
``.require()``, directly or through a name bound from one. The guard fails on
planted violations, so it cannot pass by matching nothing.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Self, final

_SRC = Path(__file__).resolve().parents[2] / "src" / "punt_lux"
_HUB = "domain/hub/"

# The modules that own the send path: the client that defines the surface and its
# outbound half, the dial the writes land on, the batch sender the replicator
# drives and the presentation it pushes, and the registry's connect-time manifest.
_SENDER_MODULES = frozenset(
    {
        _HUB + "display_link.py",
        _HUB + "display_requests.py",
        _HUB + "dial_generation.py",
        _HUB + "scene_presentation.py",
        _HUB + "batch_sender.py",
        _HUB + "clients.py",
    }
)
# What marks a receiver as the display's: reached through one of these.
_DISPLAY_PATHS = frozenset({"requests", "dial", "require"})
# A reply-waiting registration: a send that makes one is a request, not a write.
_EXPECTATIONS = frozenset({"expect_pong", "expect_query"})


def _class(tree: ast.Module, name: str) -> ast.ClassDef:
    return next(
        n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == name
    )


def _methods(cls: ast.ClassDef) -> dict[str, ast.FunctionDef]:
    return {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}


def _attrs_named(node: ast.AST) -> set[str]:
    """Every attribute the node names, called or handed on as a callable."""
    return {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}


def _attrs_called(node: ast.AST) -> set[str]:
    return {
        n.func.attr
        for n in ast.walk(node)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }


@final
class WriteVerbs:
    """The names a display write goes by, read from the classes that define them."""

    _verbs: frozenset[str]
    __slots__ = ("_verbs",)

    def __new__(cls, requests_src: str, dial_src: str) -> Self:
        self = super().__new__(cls)
        dial = _methods(_class(ast.parse(dial_src), "DialGeneration"))
        dial_writes = {
            name
            for name, fn in dial.items()
            if name.startswith("send") and not _attrs_named(fn) & _EXPECTATIONS
        }
        requests = _methods(_class(ast.parse(requests_src), "DisplayRequests"))
        public = {
            name
            for name, fn in requests.items()
            if not name.startswith("_")
            and self._reaches(fn, requests, dial_writes, set())
        }
        self._verbs = frozenset(public | dial_writes)
        return self

    @property
    def names(self) -> frozenset[str]:
        """Every verb that writes to the display."""
        return self._verbs

    @classmethod
    def _reaches(
        cls,
        fn: ast.FunctionDef,
        methods: dict[str, ast.FunctionDef],
        writes: set[str],
        seen: set[str],
    ) -> bool:
        """Whether ``fn`` calls a write, directly or through ``self._helper``."""
        called = _attrs_called(fn)
        if called & writes:
            return True
        seen.add(fn.name)
        return any(
            cls._reaches(methods[name], methods, writes, seen)
            for name in called
            if name.startswith("_") and name in methods and name not in seen
        )


@final
class DisplayWriteScan:
    """Finds, in one module's source, the calls that write to the display."""

    _verbs: frozenset[str]
    __slots__ = ("_verbs",)

    def __new__(cls, verbs: frozenset[str]) -> Self:
        self = super().__new__(cls)
        self._verbs = verbs
        return self

    def writes(self, source: str) -> list[str]:
        """Return ``verb@line`` for each display write the source makes."""
        tree = ast.parse(source)
        bound = self._bound_to_the_display(tree)
        return [
            f"{call.func.attr}@{call.lineno}"
            for call in ast.walk(tree)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Attribute)
            and call.func.attr in self._verbs
            and self._is_the_display(call.func.value, bound)
        ]

    @classmethod
    def _bound_to_the_display(cls, tree: ast.Module) -> set[str]:
        """Names assigned from an expression reached through the display's paths."""
        return {
            target.id
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign) and cls._is_the_display(node.value, set())
            for target in node.targets
            if isinstance(target, ast.Name)
        }

    @staticmethod
    def _is_the_display(expr: ast.expr, bound: set[str]) -> bool:
        for part in ast.walk(expr):
            if isinstance(part, ast.Attribute) and part.attr in _DISPLAY_PATHS:
                return True
            if isinstance(part, ast.Name) and part.id in bound:
                return True
        return False


def _verbs() -> WriteVerbs:
    return WriteVerbs(
        (_SRC / _HUB / "display_requests.py").read_text(encoding="utf-8"),
        (_SRC / _HUB / "dial_generation.py").read_text(encoding="utf-8"),
    )


class TestTheWriteVerbsAreDerived:
    def test_the_derived_verbs_are_the_writes_and_not_the_requests(self) -> None:
        names = _verbs().names

        assert {"send", "send_scene", "set_menu", "set_callback_menus"} <= names
        assert {"send_manifest", "show"} <= names
        assert names.isdisjoint({"ping", "query", "send_ping", "send_query"})


class TestNoModuleOutsideTheSenderSetWritesToTheDisplay:
    def test_the_whole_package_is_clean(self) -> None:
        scan = DisplayWriteScan(_verbs().names)
        offenders: list[str] = []
        scanned = 0
        for path in _SRC.rglob("*.py"):
            scanned += 1
            rel = path.relative_to(_SRC).as_posix()
            if rel in _SENDER_MODULES:
                continue
            offenders += [
                f"{rel}: {w}" for w in scan.writes(path.read_text(encoding="utf-8"))
            ]
        assert scanned > 0, "guard scanned no files — the source glob is broken"
        assert offenders == [], (
            "a module outside the sender set writes to the display directly; only "
            f"the replicator's send path may write to the connection: {offenders}"
        )

    def test_the_replicator_is_the_writer(self) -> None:
        # The positive side: the batch sender drives the send through the
        # snapshot's ``push``, and the shared ScenePresentation.push does the
        # scene send. If these move, the guard above must be revisited too.
        sender = (_SRC / _HUB / "batch_sender.py").read_text(encoding="utf-8")
        presentation = (_SRC / _HUB / "scene_presentation.py").read_text(
            encoding="utf-8"
        )
        assert "snapshot.push(" in sender
        assert ".send_scene(" in presentation


class TestTheGuardFailsOnAPlantedViolation:
    _SCAN = DisplayWriteScan(frozenset({"send", "send_scene", "set_menu", "show"}))

    def test_a_menu_set_through_the_registry_link(self) -> None:
        planted = "def tool(self):\n    self._clients.get().requests.set_menu([])\n"

        assert self._SCAN.writes(planted) == ["set_menu@2"]

    def test_a_generic_send_on_the_current_dial(self) -> None:
        planted = "def tool(self, msg):\n    self._connection.require().send(msg)\n"

        assert self._SCAN.writes(planted) == ["send@2"]

    def test_a_write_through_a_name_bound_from_the_port(self) -> None:
        planted = (
            "def tool(self):\n    port = self._link.requests\n    port.show('s', [])\n"
        )

        assert self._SCAN.writes(planted) == ["show@3"]

    def test_the_same_verb_on_something_that_is_not_the_display_is_clean(self) -> None:
        planted = "def tool(self, request):\n    return self._menus.set_menu(request)\n"

        assert self._SCAN.writes(planted) == []
