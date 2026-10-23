"""Presence is written only through ``ClientLifecycle``: a structural guard.

A write to a session's listener slot or its callbacks changes who the Clients menu
lists, so it owes the Hub a mark and a bound sink, paid under the store lock. Only
``ClientLifecycle`` pays that. The registry therefore hands its write surface
(``ListenerLegs``) away exactly once, to the lifecycle, and no other module may
reach it. This reads the source rather than trusting a convention.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from punt_lux.domain.hub.hub_clients import HubClientRegistry

_SRC = Path(__file__).resolve().parents[2] / "src" / "punt_lux"
_TESTS = Path(__file__).resolve().parents[1]
_WRITES = {"attach", "register_callback", "detach"}

# The unit tests of the legs and of the lock order take a registry's legs on their own.
_LEG_UNIT_TESTS = {"test_hub_clients.py", "test_client_lifecycle_lock_order.py"}


def _calls_of(root: Path, attribute: str) -> set[str]:
    """The files under ``root`` that call ``<expr>.<attribute>(...)``."""
    found = set()
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == attribute
            ):
                found.add(path.name)
    return found


def _leg_writes(root: Path) -> set[str]:
    """The files under ``root`` that write through something named ``*legs``."""
    found = set()
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr in _WRITES
                and isinstance(node.func.value, ast.Attribute | ast.Name)
            ):
                owner = node.func.value
                name = owner.attr if isinstance(owner, ast.Attribute) else owner.id
                if name.endswith("legs"):
                    found.add(path.name)
    return found


def test_only_the_lifecycle_writes_through_the_legs_in_the_source() -> None:
    assert _leg_writes(_SRC) == {"client_lifecycle.py"}


def test_only_the_store_factory_takes_the_legs_in_the_source() -> None:
    assert _calls_of(_SRC, "take_legs") == {"hub_store_factory.py"}


def test_no_test_outside_the_leg_unit_tests_takes_or_writes_the_legs() -> None:
    taken = _calls_of(_TESTS, "take_legs") - {Path(__file__).name}
    written = _leg_writes(_TESTS) - {Path(__file__).name}

    assert taken <= _LEG_UNIT_TESTS
    assert written <= _LEG_UNIT_TESTS


def test_the_registry_gives_its_legs_away_exactly_once() -> None:
    registry = HubClientRegistry()
    registry.take_legs()

    with pytest.raises(RuntimeError, match="already handed"):
        registry.take_legs()
