"""The replicator is the only Hub-side writer to the display: by what exists.

No MCP mutation tool, click dispatch, or Hub-hosted app may send to the display:
they write ``HubDisplay`` and mark a scene dirty, and the one background replicator
does every send. That is held by construction, not by spotting calls:

- the write verbs exist on ``DisplayWriter`` and nowhere else (its public methods are
  the verbs; ``DisplayRequests``, which every part of the Hub may hold, has none and
  reaches no write of the dial);
- a writer is made at one site (``WriteSeat.current``), the seat at one site (the
  link's request desk, which only the link reaches), and the seat is given away once,
  to the one writer, through the hops (the registry takes it from its link, the
  replicator from the registry), so a second asker is refused at run time;
- the link's own writes, the manifest and the close, are the registry's and the link's
  alone: the manifest is declared inside the link's connect step (asked only by the
  registry), and only the modules that name a ``DisplayLink`` can reach its ``close``;
  what the registry hands out is the ask port, never the link;
- a dial's own write methods are reachable only by what holds a ``DialGeneration``,
  and the modules that so much as name that type are exactly the dial model's.

Each rule is read from the source and run on planted source, so none can pass by
matching nothing.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from punt_lux.domain.hub.display_link import DisplayLink
from punt_lux.domain.hub.display_requests import DisplayRequests
from punt_lux.domain.hub.display_writer import DisplayWriter
from tests.class_references import ClassReferences, aliased_constructions

if TYPE_CHECKING:
    from collections.abc import Callable

_SRC = Path(__file__).resolve().parents[2] / "src" / "punt_lux"
_HUB = "domain/hub/"

# The modules that name a ``DialGeneration``: the dial and what is built on it. A
# module outside this set cannot hold a dial, so it cannot write or read on one.
_DIAL_MODEL = frozenset(
    {
        _HUB + "dial_generation.py",
        _HUB + "dial_reader.py",
        _HUB + "dial_ref.py",
        _HUB + "display_connection.py",
        _HUB + "display_listener.py",
        _HUB + "display_replies.py",
        _HUB + "display_requests.py",
        _HUB + "display_writer.py",
        _HUB + "inbound_router.py",
        _HUB + "listener_thread.py",
        _HUB + "request_exchange.py",
    }
)
# A reply-waiting registration: a send that makes one is a request, not a write.
_EXPECTATIONS = frozenset({"expect_pong", "expect_query"})


def _source(rel: str) -> str:
    return (_SRC / rel).read_text(encoding="utf-8")


def _class(source: str, name: str) -> ast.ClassDef:
    return next(
        n
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.ClassDef) and n.name == name
    )


def _public_methods(source: str, name: str) -> dict[str, ast.FunctionDef]:
    return {
        n.name: n
        for n in _class(source, name).body
        if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")
    }


def _called(node: ast.AST) -> set[str]:
    return {
        n.func.attr
        for n in ast.walk(node)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
    }


def _attrs(node: ast.AST) -> set[str]:
    return {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}


def _names(source: str) -> set[str]:
    """Every name the source uses or imports, however it spells the reference."""
    found: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.ImportFrom | ast.Import):
            found.update(a.name.split(".")[-1] for a in node.names)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
    return found


def _constructions(source: str, name: str) -> int:
    return ClassReferences(source, name).constructions()


def _calls_of(source: str, attribute: str) -> int:
    return sum(
        1
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == attribute
    )


def _declaring_connects(source: str) -> int:
    """How many ``connect(..., manifest=...)`` calls the source makes."""
    return sum(
        1
        for n in ast.walk(ast.parse(source))
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Attribute)
        and n.func.attr == "connect"
        and any(k.arg == "manifest" for k in n.keywords)
    )


def _modules(predicate: Callable[[str], object]) -> set[str]:
    return {
        path.relative_to(_SRC).as_posix()
        for path in _SRC.rglob("*.py")
        if predicate(path.read_text(encoding="utf-8"))
    }


def _dial_writes() -> set[str]:
    """The dial's write methods: every ``send*`` that registers no reply to wait for."""
    return {
        name
        for name, fn in _public_methods(
            _source(_HUB + "dial_generation.py"), "DialGeneration"
        ).items()
        if name.startswith("send") and not _attrs(fn) & _EXPECTATIONS
    }


class TestTheWriteVerbsLiveOnTheWriterAlone:
    def test_the_writers_public_methods_are_the_write_verbs(self) -> None:
        verbs = set(
            _public_methods(_source(_HUB + "display_writer.py"), "DisplayWriter")
        )

        assert {"send_scene", "set_menu", "set_callback_menus"} <= verbs
        assert {"send_manifest"} <= verbs
        assert verbs.isdisjoint(
            {"show", "ping", "query", "probe_alive", "confirm_alive"}
        )

    def test_the_dials_write_methods_are_derived_from_the_dial(self) -> None:
        assert _dial_writes() == {"send", "send_scene"}

    def test_the_ask_port_has_no_write_verb_and_reaches_no_dial_write(self) -> None:
        source = _source(_HUB + "display_requests.py")
        verbs = set(
            _public_methods(_source(_HUB + "display_writer.py"), "DisplayWriter")
        )

        asks = set(_public_methods(source, "DisplayRequests"))
        reached = _called(_class(source, "DisplayRequests"))

        assert asks.isdisjoint(verbs - {"dial"})
        assert reached.isdisjoint(_dial_writes())


class TestWhatEveryPartOfTheHubMayHold:
    """The ask port, held by anything however it is spelled, cannot write."""

    def test_the_ask_port_has_none_of_the_writers_verbs_at_run_time(self) -> None:
        verbs = {
            name
            for name in vars(DisplayWriter)
            if not name.startswith("_") and callable(vars(DisplayWriter)[name])
        }

        assert verbs, "the writer has no verbs to withhold"
        assert [v for v in verbs if hasattr(DisplayRequests, v)] == []

    def test_the_link_hands_out_no_writer_but_through_its_seat(self) -> None:
        public = {n for n in vars(DisplayLink) if not n.startswith("_")}

        assert {"writer", "send_scene", "set_menu", "show"}.isdisjoint(public)


class TestAWriterIsMadeAtOneSiteAndGivenAwayOnce:
    def test_a_writer_is_built_only_by_the_seat(self) -> None:
        built = {
            rel: _constructions(_source(rel), "DisplayWriter")
            for rel in _modules(lambda s: _constructions(s, "DisplayWriter"))
        }

        assert built == {_HUB + "display_writer.py": 1}

    def test_the_seat_is_built_only_by_the_link_s_desk(self) -> None:
        built = {
            rel: _constructions(_source(rel), "WriteSeat")
            for rel in _modules(lambda s: _constructions(s, "WriteSeat"))
        }

        assert built == {_HUB + "request_desk.py": 1}

    def test_a_dial_is_named_only_inside_the_dial_model(self) -> None:
        built = {
            rel: _constructions(_source(rel), "DialRef")
            for rel in _modules(lambda s: _constructions(s, "DialRef"))
        }

        assert set(built) <= _DIAL_MODEL | {_HUB + "dial_ref.py"}
        assert built == {
            _HUB + "display_connection.py": 1,
            _HUB + "request_exchange.py": 1,
        }

    def test_the_seat_is_taken_only_where_it_is_handed_on(self) -> None:
        # The registry takes it from its link's desk; the replicator from the registry.
        assert _modules(lambda s: _calls_of(s, "take_seat") > 0) == {
            _HUB + "clients.py"
        }
        assert _modules(lambda s: _calls_of(s, "take_writer") > 0) == {
            _HUB + "replicator.py"
        }

    def test_each_hop_takes_the_seat_once(self) -> None:
        assert _calls_of(_source(_HUB + "clients.py"), "take_seat") == 1
        assert _calls_of(_source(_HUB + "replicator.py"), "take_writer") == 1


class TestTheLinkIsTheRegistrysAlone:
    """The manifest and the close are not the ask port's, nor any caller's."""

    def test_the_manifest_is_declared_only_inside_the_links_connect_step(self) -> None:
        assert _modules(lambda s: _calls_of(s, "declare") > 0) == {
            _HUB + "display_link.py"
        }
        assert _calls_of(_source(_HUB + "display_link.py"), "declare") == 1

    def test_the_connect_step_that_declares_is_asked_only_by_the_registry(
        self,
    ) -> None:
        assert _modules(lambda s: _declaring_connects(s) > 0) == {_HUB + "clients.py"}
        assert _declaring_connects(_source(_HUB + "clients.py")) == 1

    def test_only_the_registry_and_the_links_own_modules_name_a_link(self) -> None:
        naming = _modules(lambda s: "DisplayLink" in _names(s))

        assert naming == {
            _HUB + "clients.py",
            _HUB + "cross_host_link.py",
            _HUB + "display_link.py",
        }

    def test_the_registry_hands_out_no_link(self) -> None:
        public = _public_methods(_source(_HUB + "clients.py"), "ClientRegistry")

        assert "get" not in public
        assert "asks" in public

    def test_the_link_declares_through_its_connect_step_and_keeps_no_declare(
        self,
    ) -> None:
        public = {n for n in vars(DisplayLink) if not n.startswith("_")}

        assert "declare" not in public
        assert "connect" in public

    def test_a_second_declarer_and_a_second_naming_of_the_link_are_found(self) -> None:
        planted_declare = "def f(clients):\n    clients.link.desk.declare(())\n"
        planted_connect = "def f(link):\n    link.connect(listen=True, manifest=m)\n"
        planted_naming = (
            "from punt_lux.domain.hub.display_link import DisplayLink as L\n"
        )

        assert _calls_of(planted_declare, "declare") == 1
        assert _declaring_connects(planted_connect) == 1
        assert _declaring_connects("def f(link):\n    link.connect(listen=True)\n") == 0
        assert "DisplayLink" in _names(planted_naming)


class TestOnlyTheDialModelCanHoldADial:
    def test_the_modules_that_name_a_dial_are_the_dial_models(self) -> None:
        naming = _modules(lambda s: "DialGeneration" in _names(s))

        assert naming == _DIAL_MODEL

    def test_a_module_that_names_a_dial_in_any_spelling_is_found(self) -> None:
        for planted in (
            "from punt_lux.domain.hub.dial_generation import DialGeneration\n",
            "import punt_lux.domain.hub.dial_generation as g\nx = g.DialGeneration\n",
            "def f(dial: DialGeneration) -> None:\n    dial.send(None)\n",
        ):
            assert "DialGeneration" in _names(planted), planted


class TestTheRulesCanFail:
    def test_a_second_writer_construction_is_counted(self) -> None:
        planted = "def f(g):\n    return DisplayWriter(g, None, None)\n"

        assert _constructions(planted, "DisplayWriter") == 1

    @pytest.mark.parametrize("name", ["DisplayWriter", "WriteSeat"])
    def test_an_aliased_construction_is_counted(self, name: str) -> None:
        for planted in aliased_constructions("punt_lux.domain.hub.x", name):
            assert _constructions(planted, name) == 1, planted

    def test_a_second_seat_taker_is_found(self) -> None:
        planted = "def f(clients):\n    return clients.take_writer()\n"

        assert _calls_of(planted, "take_writer") == 1

    def test_a_write_verb_on_the_ask_port_is_found(self) -> None:
        planted = (
            "class DisplayRequests:\n"
            "    def set_menu(self, menus):\n"
            "        self._generation.send(menus)\n"
        )
        asks = set(_public_methods(planted, "DisplayRequests"))

        assert asks & {"set_menu", "send_scene"} == {"set_menu"}
        assert "send" in _called(_class(planted, "DisplayRequests"))

    def test_a_new_dial_write_enters_the_derived_set(self) -> None:
        planted = (
            "class DialGeneration:\n"
            "    def send_raw(self, data):\n"
            "        self._sock.sendall(data)\n"
            "    def send_probe(self, ts):\n"
            "        return self._sink.expect_pong(ts)\n"
        )
        writes = {
            name
            for name, fn in _public_methods(planted, "DialGeneration").items()
            if name.startswith("send") and not _attrs(fn) & _EXPECTATIONS
        }

        assert writes == {"send_raw"}

    @pytest.mark.parametrize("name", ["DisplayWriter", "WriteSeat"])
    def test_the_capability_classes_exist_to_be_counted(self, name: str) -> None:
        assert _class(_source(_HUB + "display_writer.py"), name)
