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

# Three ways a module reaches the socket client, each with its own pattern.
# IMPORT covers every spelling that brings the name or its module into scope:
# ``from ...display_client import DisplayClient``, the whole-module
# ``import ...display_client`` (aliased or not), and ``from punt_lux import
# display_client``. CONSTRUCT matches the call on any receiver, so
# ``dc.DisplayClient(`` is caught. REFERENCE matches attribute access to the
# class without a call — subclassing ``display_client.DisplayClient`` or naming
# it in an annotation — which neither of the others would see. Docstrings write
# ``DisplayClient`` in backticks or as ``DisplayClient.method`` (dot *after*),
# so no pattern matches prose — only real use.
_IMPORT_RE = re.compile(
    r"^\s*(?:from punt_lux\.display_client import [^\n]*\bDisplayClient\b"
    r"|import punt_lux\.display_client\b"
    r"|from punt_lux import [^\n]*\bdisplay_client\b)",
    re.MULTILINE,
)
_CONSTRUCT_RE = re.compile(r"\bDisplayClient\s*\(")
_REFERENCE_RE = re.compile(r"\.DisplayClient\b")


def _scan() -> tuple[list[str], int]:
    """Return (offenders, files_scanned) over the package source."""
    offenders: list[str] = []
    scanned = 0
    checks = (
        (_IMPORT_RE, "imports DisplayClient"),
        (_CONSTRUCT_RE, "constructs DisplayClient"),
        (_REFERENCE_RE, "references DisplayClient"),
    )
    for path in _SRC.rglob("*.py"):
        scanned += 1
        rel = path.relative_to(_SRC).as_posix()
        if rel in _ALLOWED:
            continue
        source = path.read_text(encoding="utf-8")
        offenders.extend(f"{rel}: {label}" for rx, label in checks if rx.search(source))
    return offenders, scanned


def test_only_the_hub_layer_opens_the_display_socket() -> None:
    offenders, scanned = _scan()
    assert scanned > 0, "guard scanned no files — the source glob is broken"
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


def test_the_guard_patterns_fire_on_offending_forms() -> None:
    # Prove the regexes catch every real reach-around shape, so a green scan
    # means "no offender", not "the pattern never matches anything".
    from_import = "from punt_lux.display_client import DisplayClient\n"
    aliased_module = "import punt_lux.display_client as dc\n\ndc.DisplayClient(sock)\n"
    package_import = "from punt_lux import display_client\n"
    subclass = "class Fake(display_client.DisplayClient):\n    pass\n"
    bare_construct = "with DisplayClient(sock) as c:\n    ...\n"
    assert _IMPORT_RE.search(from_import)
    assert _IMPORT_RE.search(aliased_module)  # whole-module import caught
    assert _IMPORT_RE.search(package_import)  # from-package module import caught
    assert _CONSTRUCT_RE.search(aliased_module)  # dotted construction caught
    assert _CONSTRUCT_RE.search(bare_construct)
    # Attribute access with no call — subclassing via a module alias — is caught
    # by the reference arm even though nothing is constructed on this line.
    assert _REFERENCE_RE.search(subclass)
    assert not _CONSTRUCT_RE.search(subclass)

    # A prose mention with backticks and an attribute access must NOT fire.
    prose = "See :class:`DisplayClient` and DisplayClient.poll_event for details.\n"
    assert not _IMPORT_RE.search(prose)
    assert not _CONSTRUCT_RE.search(prose)
    assert not _REFERENCE_RE.search(prose)
