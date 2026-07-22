"""The display socket is Hub-internal: luxd is its only client.

After the CLI moved onto luxd's REST API, nothing but luxd's own Hub layer may
open the display connection. ``DisplayClient`` is the surface that opens that
socket, so this guard reads the whole package source and fails if any module
outside the allowed set imports or constructs it. A new reach-around — a CLI
command, an app, a tool talking to the display directly — cannot slip back in
through a module an enumerated list would have forgotten.

The allowed set is named explicitly and is deliberately minimal: the module that
defines the client, and the one Hub-layer registry that owns luxd's single lazy
connection. The e2e/business harness drives the in-memory ``Connection`` rather
than the socket, so it is not a client of this surface and is not listed.
"""

from __future__ import annotations

import re
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src" / "punt_lux"

# display_client.py defines DisplayClient; domain/hub/clients.py owns luxd's one
# lazy connection to the display. No other module may import or construct it.
_ALLOWED = frozenset({"display_client.py", "domain/hub/clients.py"})

# The two ways a module reaches the socket client: importing the name, or
# constructing it. Docstrings reference ``DisplayClient`` in backticks with no
# import line and no call, so neither pattern matches prose — only real use.
_IMPORT_RE = re.compile(
    r"^\s*from punt_lux\.display_client import [^\n]*\bDisplayClient\b", re.MULTILINE
)
_CONSTRUCT_RE = re.compile(r"\bDisplayClient\s*\(")


def test_only_the_hub_layer_opens_the_display_socket() -> None:
    offenders: list[str] = []
    for path in _SRC.rglob("*.py"):
        rel = path.relative_to(_SRC).as_posix()
        if rel in _ALLOWED:
            continue
        source = path.read_text(encoding="utf-8")
        if _IMPORT_RE.search(source):
            offenders.append(f"{rel}: imports DisplayClient")
        if _CONSTRUCT_RE.search(source):
            offenders.append(f"{rel}: constructs DisplayClient")
    assert offenders == [], (
        "the display socket has more than one client; only luxd's Hub layer "
        f"({sorted(_ALLOWED)}) may open the display connection: {offenders}"
    )


def test_the_hub_layer_is_the_client() -> None:
    # The positive side: the allowed registry does construct the client, so the
    # guard above is checking a live invariant, not an empty set. If the Hub
    # connection moves, this fails and the allowed set must be revisited.
    clients = (_SRC / "domain/hub/clients.py").read_text(encoding="utf-8")
    assert _CONSTRUCT_RE.search(clients), "the Hub client registry must own the socket"
