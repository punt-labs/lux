"""The display socket is Hub-internal: luxd is its only client.

After the CLI moved onto luxd's REST API, nothing but luxd's own Hub layer may
open the display connection. ``DisplayLink`` is the surface that opens that
socket, so this guard reads the whole package source and fails if any module
outside the allowed set imports or references it. A new reach-around — a CLI
command, an app, a tool talking to the display directly — cannot slip back in
through a module an enumerated list would have forgotten.

The allowed set is named explicitly and is deliberately minimal: the module that
defines the client, and the one Hub-layer registry that owns luxd's single lazy
connection. The e2e/business harness drives the in-memory ``Connection`` rather
than the socket, so it is not a client of this surface and is not listed.

Detection is by AST, not by regex. Every spelling of "reach the client" — an
absolute or relative import, aliased, single- or multi-line parenthesized, a
whole-module import that puts the class within attribute reach, and any bare or
attribute reference to ``DisplayLink`` — is one of a small, closed set of AST
node shapes. A line-scoped regex chased those shapes one bypass at a time (a
multi-line import was the fourth); the parse tree sees them all at once. A
mention in a docstring or comment is a string constant or absent from the tree,
so the walk never mistakes prose for use — no negative pattern needed.

Importing a plain value from the module (for example ``DEFAULT_RECV_TIMEOUT``)
does not open the socket, so only the ``DisplayLink`` name — imported or
referenced — is an offence.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src" / "punt_lux"

# domain/hub/display_link.py defines DisplayLink; domain/hub/clients.py owns luxd's one
# lazy connection to the display. No other module may import or reference it.
_ALLOWED = frozenset({"domain/hub/display_link.py", "domain/hub/clients.py"})

_MODULE = "display_link"  # last segment of punt_lux.domain.hub.display_link
_CLASS = "DisplayLink"


def _module_tail(node: ast.ImportFrom) -> str:
    """Last dotted segment of an ImportFrom's module; '' for a bare ``from .``."""
    return node.module.split(".")[-1] if node.module else ""


def _import_from_reason(node: ast.ImportFrom) -> str:
    """Reason an ``ImportFrom`` reaches the client, or '' if it does not.

    ``from …display_link import DisplayLink`` (absolute or relative, any
    alias) imports the class; ``from … import display_link`` imports the module
    wholesale. Importing a plain value from the module (``DEFAULT_RECV_TIMEOUT``)
    is neither, and returns ''.
    """
    if _module_tail(node) == _MODULE:
        return (
            "imports DisplayLink" if any(a.name == _CLASS for a in node.names) else ""
        )
    if any(a.name == _MODULE for a in node.names):
        return "imports the display_link module"
    return ""


def _node_reason(node: ast.AST) -> str:
    """Reason a single AST node reaches the display socket client, or ''."""
    if isinstance(node, ast.ImportFrom):
        return _import_from_reason(node)
    if isinstance(node, ast.Import):
        tails = (a.name.split(".")[-1] for a in node.names)
        return "imports the display_link module" if _MODULE in tails else ""
    if isinstance(node, ast.Name) and node.id == _CLASS:
        return "references DisplayLink"
    if isinstance(node, ast.Attribute) and node.attr == _CLASS:
        return "references DisplayLink"
    return ""


def _display_link_uses(source: str) -> list[str]:
    """Return the ways ``source`` reaches the display socket client, by AST walk.

    Flags importing the ``DisplayLink`` class (absolute or relative, any alias,
    single- or multi-line parenthesized), importing the ``display_link`` module
    wholesale (which puts the class within attribute reach), and any bare or
    attribute reference to ``DisplayLink``. Docstrings and comments are string
    constants or absent from the tree, so a mention in prose is never a use.
    """
    reasons = (_node_reason(node) for node in ast.walk(ast.parse(source)))
    return [reason for reason in reasons if reason]


def _scan() -> tuple[list[str], int]:
    """Return (offenders, files_scanned) over the package source."""
    offenders: list[str] = []
    scanned = 0
    for path in _SRC.rglob("*.py"):
        scanned += 1
        rel = path.relative_to(_SRC).as_posix()
        if rel in _ALLOWED:
            continue
        source = path.read_text(encoding="utf-8")
        offenders.extend(f"{rel}: {reason}" for reason in _display_link_uses(source))
    return offenders, scanned


def test_only_the_hub_layer_opens_the_display_socket() -> None:
    offenders, scanned = _scan()
    assert scanned > 0, "guard scanned no files — the source glob is broken"
    assert offenders == [], (
        "the display socket has more than one client; only luxd's Hub layer "
        f"({sorted(_ALLOWED)}) may open the display connection: {offenders}"
    )


def test_the_hub_layer_is_the_client() -> None:
    # The positive side: the allowed registry does reach the client, so the guard
    # above is checking a live invariant, not an empty set. If the Hub connection
    # moves, this fails and the allowed set must be revisited.
    clients = (_SRC / "domain/hub/clients.py").read_text(encoding="utf-8")
    assert _display_link_uses(clients), "the Hub client registry must own the socket"


def test_the_guard_flags_every_offending_form() -> None:
    # Every reach-around shape fires through the AST walk, so a green scan means
    # "no offender", not "the pattern never matches". The multi-line parenthesized
    # import is the form that slipped the old line-scoped regex.
    forms = (
        "from punt_lux.domain.hub.display_link import DisplayLink\n",
        "from punt_lux.domain.hub.display_link import (\n    DisplayLink,\n)\n",
        "from .display_link import DisplayLink as DC\n\nDC(sock)\n",
        "from ...display_link import DisplayLink\n",
        "from . import display_link\n",
        "from punt_lux.domain.hub import display_link\n",
        "import punt_lux.domain.hub.display_link as dc\n\ndc.DisplayLink(sock)\n",
        "with DisplayLink(sock) as c:\n    ...\n",
        "class Fake(display_link.DisplayLink):\n    pass\n",
    )
    for src in forms:
        assert _display_link_uses(src), f"guard missed: {src!r}"


def test_the_guard_ignores_prose_and_value_imports() -> None:
    # A docstring or comment mention is a string constant or absent from the AST,
    # never a use — this is free with an AST walk, no negative pattern required.
    assert not _display_link_uses(
        '""":class:`DisplayLink` and DisplayLink.poll_event for details."""\n'
    )
    assert not _display_link_uses("# see DisplayLink for details\n")
    # Importing a plain value from the module is not opening the socket.
    assert not _display_link_uses(
        "from punt_lux.domain.hub.display_link import DEFAULT_RECV_TIMEOUT\n"
    )
