"""The replicator is the only Hub-side writer to the display connection.

After the liveness change, no MCP mutation tool, click dispatch, or Hub-hosted
app may send to the display — they write ``HubDisplay`` and mark a scene dirty,
and the one background replicator does every send. This guard reads the source of
the front-door modules and fails if a display send reappears in any of them, so
the single-writer invariant cannot regress silently.
"""

from __future__ import annotations

from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "src" / "punt_lux"

# The front-door modules an agent's call or a click flows through. None may
# send to the display; each must go through the store and the replicator.
_FRONT_DOOR_MODULES = (
    "tools/tools.py",
    "tools/subscribe_tools.py",
    "domain/hub/clients.py",
    "domain/hub/scene_writer.py",
    "apps/beads.py",
)

# The DisplayClient send surface — calling any of these is "writing to the
# display". Only the replicator (via ScenePresentation.push and clear_async) may.
_SEND_CALLS = (".show_async(", ".clear_async(", "client.show(", "client.clear(")


def test_no_front_door_module_sends_to_the_display() -> None:
    offenders: list[str] = []
    for module in _FRONT_DOOR_MODULES:
        source = (_SRC / module).read_text(encoding="utf-8")
        offenders.extend(f"{module}: {call}" for call in _SEND_CALLS if call in source)
    assert offenders == [], (
        "a front-door module sends to the display directly; only the replicator "
        f"may write to the display connection: {offenders}"
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
