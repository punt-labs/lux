"""The replicator is the only Hub-side writer to the display connection.

After the liveness change, no MCP mutation tool, click dispatch, or Hub-hosted
app may send to the display — they write ``HubDisplay`` and mark a scene dirty,
and the one background replicator does every send. This guard reads the source of
the front-door modules and fails if a display send reappears in any of them, so
the single-writer invariant cannot regress silently.
"""

from __future__ import annotations

import re
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src" / "punt_lux"

# The only modules allowed to reference the display send surface: the client that
# defines it, the replicator's send path (replicator + the presentation it
# drives), and the ``lux show`` CLI, which is a separate short-lived process that
# renders directly as a display client, not a Hub-side mutation path. Every other
# module — every MCP tool, every click dispatch, every Hub-hosted app — must go
# through the store and the dirty signal, so the guard scans the whole package
# and a new Hub-side sender cannot slip in through a module an enumerated list
# would have forgotten.
_SENDER_MODULES = frozenset(
    {
        "display_client.py",
        "domain/hub/scene_presentation.py",
        "domain/hub/replicator.py",
        "show.py",
    }
)

# The DisplayClient send surface — a call to any of these is "writing to the
# display". The word boundary on ``client`` keeps a dict ``.clear()`` (e.g.
# ``_fd_to_client.clear()``) from matching the blocking ``client.clear()`` send.
_SEND_CALL_RE = re.compile(r"\.(?:show_async|clear_async)\(|\bclient\.(?:show|clear)\(")


def test_no_module_outside_the_sender_set_writes_to_the_display() -> None:
    offenders: list[str] = []
    for path in _SRC.rglob("*.py"):
        rel = path.relative_to(_SRC).as_posix()
        if rel in _SENDER_MODULES:
            continue
        source = path.read_text(encoding="utf-8")
        offenders.extend(f"{rel}: {m.group()}" for m in _SEND_CALL_RE.finditer(source))
    assert offenders == [], (
        "a module outside the sender set writes to the display directly; only the "
        f"replicator's send path may write to the display connection: {offenders}"
    )


def test_the_replicator_is_the_writer() -> None:
    # The positive side: the replicator does send (clear_async), and the shared
    # ScenePresentation.push it drives does the scene send (show_async). If these
    # move, the guard above must be revisited too.
    replicator = (_SRC / "domain/hub/replicator.py").read_text(encoding="utf-8")
    presentation = (_SRC / "domain/hub/scene_presentation.py").read_text(
        encoding="utf-8"
    )
    assert ".clear_async()" in replicator
    assert ".show_async(" in presentation
