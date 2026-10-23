"""Presence is written only through ``ClientLifecycle``: a structural guard.

A write to a session's record, lease, listener slot or callbacks changes who the
Clients menu lists, so it owes the Hub a mark and a bound sink, paid under the
store lock. Only ``ClientLifecycle`` pays that. The registry therefore hands its
write surface (``PresenceWrites``) away exactly once, to the lifecycle, and no other
module may import or take it. This reads the source rather than trusting a
convention; the write set is derived from ``PresenceWrites``' own public methods.
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from punt_lux.domain.hub.hub_clients import HubClientRegistry
from punt_lux.domain.hub.presence_writes import PresenceWrites

_SRC = Path(__file__).resolve().parents[2] / "src" / "punt_lux"
_TESTS = Path(__file__).resolve().parents[1]
_WRITES = {
    name
    for name in dict(inspect.getmembers(PresenceWrites, inspect.isfunction))
    if not name.startswith("_")
}

# The registry hands the surface out and the lifecycle takes it.
_IMPORTERS = {"hub_clients.py", "client_lifecycle.py", "presence_writes.py"}
# The unit tests of the writes and of the lock order take a registry's writes on
# their own.
_WRITE_UNIT_TESTS = {"test_hub_clients.py", "test_client_lifecycle_lock_order.py"}


def _parsed(root: Path) -> list[tuple[str, ast.AST]]:
    return [(path.name, ast.parse(path.read_text())) for path in root.rglob("*.py")]


def _importers(root: Path) -> set[str]:
    """The files under ``root`` that import ``PresenceWrites`` from its module."""
    return {
        name
        for name, tree in _parsed(root)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module == "punt_lux.domain.hub.presence_writes"
        and any(alias.name == "PresenceWrites" for alias in node.names)
    }


def _calls_of(root: Path, attribute: str) -> set[str]:
    """The files under ``root`` that call ``<expr>.<attribute>(...)``."""
    return {
        name
        for name, tree in _parsed(root)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == attribute
    }


def _written_through_writes(root: Path) -> set[str]:
    """The files that call a presence write on something named ``*writes``."""
    found: set[str] = set()
    for name, tree in _parsed(root):
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _WRITES
                and isinstance(node.func.value, ast.Attribute | ast.Name)
            ):
                owner = node.func.value
                label = owner.attr if isinstance(owner, ast.Attribute) else owner.id
                if label.lstrip("_").endswith("writes"):
                    found.add(name)
    return found


def test_the_write_set_is_derived_from_the_writes_public_methods() -> None:
    assert {
        "record",
        "renew_if_registered",
        "discard",
        "reap_lapsed",
        "attach",
        "detach",
        "register_callback",
    } <= _WRITES


def test_only_the_registry_and_the_lifecycle_import_the_writes_in_the_source() -> None:
    assert _importers(_SRC) == _IMPORTERS - {"presence_writes.py"}


def test_only_the_lifecycle_takes_the_writes_in_the_source() -> None:
    assert _calls_of(_SRC, "take_writes") == {"client_lifecycle.py"}


def test_only_the_lifecycle_writes_through_the_writes_in_the_source() -> None:
    assert _written_through_writes(_SRC) == {"client_lifecycle.py"}


def test_no_test_outside_the_write_unit_tests_takes_or_writes_the_writes() -> None:
    me = Path(__file__).name
    taken = _calls_of(_TESTS, "take_writes") - {me}
    written = _written_through_writes(_TESTS) - {me}
    imported = _importers(_TESTS) - {me}

    assert taken <= _WRITE_UNIT_TESTS
    assert written <= _WRITE_UNIT_TESTS
    assert imported <= _WRITE_UNIT_TESTS


def test_the_registry_has_no_write_of_its_own() -> None:
    own = {name for name in vars(HubClientRegistry) if not name.startswith("_")}

    assert own.isdisjoint(_WRITES)


def test_the_registry_gives_its_writes_away_exactly_once() -> None:
    registry = HubClientRegistry()
    registry.take_writes()

    with pytest.raises(ValueError, match="already handed"):
        registry.take_writes()
