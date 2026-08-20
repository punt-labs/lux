"""The CLI parity guard: every non-admin commands/ singleton has a Typer entry.

Mirrors the REST route-parity guard (``tests/rest/test_app.py``): a new
command added to ``commands/`` with no CLI verb and no exemption fails this
test, so the CLI cannot silently fall behind the engine. The exemption set
mirrors the REST guard's ``_MCP_ONLY`` for the same reason -- these commands
have no REST route because they cannot (a stateless request cannot bind to
the listen leg's delivery), so a REST-backed CLI verb has the identical
problem.
"""

from __future__ import annotations

import re
from pathlib import Path

import click
import typer.main

from punt_lux import commands
from punt_lux.__main__ import app

# Commands with no REST route by ratified design (tests/rest/test_app.py
# _MCP_ONLY) -- delivery for these runs over the listen leg's push/drain,
# which a stateless HTTP request (the CLI's only transport) cannot bind to.
_CLI_UNREACHABLE = {
    "topic_publish",
    "topic_subscribe",
    "topic_unsubscribe",
    "topic_recv",
    "callback_pending",
}

_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "punt_lux"


def _command_singleton_names() -> set[str]:
    """Every command singleton exported from ``commands/__init__.py``.

    Distinguished from the ops Protocols and shared types by case: every
    command singleton is a lowercase module-level instance
    (``scene_show``, ``ping``); every Protocol/type export is PascalCase
    (``SceneOps``, ``CommandResult``, ``Ctx``).
    """
    return {name for name in commands.__all__ if name[:1].islower()}


def _cli_source_text() -> str:
    """The concatenated source of every CLI module that can wire a command."""
    paths = [*(_SRC_ROOT / "cli").glob("*.py"), _SRC_ROOT / "__main__.py"]
    return "\n".join(p.read_text() for p in paths)


def _wired_commands() -> set[str]:
    """Command singleton names that appear as identifiers in the CLI source."""
    source = _cli_source_text()
    names = _command_singleton_names()
    return {name for name in names if re.search(rf"\b{re.escape(name)}\b", source)}


def _typer_command_paths() -> set[tuple[str, ...]]:
    """Every reachable command path in the root Typer app, as a tuple of words.

    E.g. ``lux scene show`` -> ``("scene", "show")``, ``lux ping`` -> ``("ping",)``.
    """
    root = typer.main.get_command(app)
    paths: set[tuple[str, ...]] = set()

    def walk(cmd: click.Command, prefix: tuple[str, ...]) -> None:
        if isinstance(cmd, click.Group):
            for name, sub in cmd.commands.items():
                walk(sub, (*prefix, name))
        else:
            paths.add(prefix)

    walk(root, ())
    return paths


def test_every_command_singleton_is_wired_or_exempt() -> None:
    wired = _wired_commands()
    names = _command_singleton_names()
    unwired = names - wired - _CLI_UNREACHABLE
    assert unwired == set(), f"commands/ singletons with no CLI verb: {unwired}"


def test_exempt_set_names_only_real_commands() -> None:
    # A stale exemption (a command that no longer exists) would silently mask
    # a missing verb; keep the set honest.
    assert _command_singleton_names() >= _CLI_UNREACHABLE


def test_wired_and_exempt_sets_are_disjoint() -> None:
    # A command cannot be both wired and CLI-unreachable-exempt: if it were,
    # losing its verb would leave this guard green (the exemption would mask
    # the gap).
    assert _wired_commands().isdisjoint(_CLI_UNREACHABLE)


def test_root_app_exposes_at_least_one_command_per_noun_group() -> None:
    # A sanity floor: every noun group module wires at least one real Typer
    # command reachable from the root app -- catches a group created but
    # never composed with app.add_typer().
    paths = _typer_command_paths()
    nouns = {path[0] for path in paths if len(path) > 1}
    expected_nouns = {
        "scene",
        "frame",
        "menu",
        "session",
        "display",
        "event",
        "error",
        "callback",
        "hub",
    }
    missing = expected_nouns - nouns
    assert missing == set(), f"noun groups with zero reachable commands: {missing}"
