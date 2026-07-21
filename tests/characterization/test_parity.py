"""Snapshot parity test — every recorded snapshot replays identically.

This is the executable form of the characterization safety net. Every JSON
file in ``tests/characterization/snapshots/`` is loaded as a :class:`Snapshot`,
fed to :class:`ToolExerciser`, and the live response is compared to the recorded
response.

When a tool's wire-level output drifts — even by one byte — the test fails with
a unified diff showing exactly what changed. ``make snapshot-parity`` is the
same assertion as a make target.

Manual regression check: pick any tool the corpus covers, deliberately break it
by editing one character in ``src/punt_lux/tools/tools.py`` (e.g., change
``"shown:"`` to ``"SHOWN:"`` in the ``show`` tool's success branch), then run::

    make snapshot-parity

The target exits non-zero. The pytest output names every failing
snapshot and embeds ``Snapshot.diff(observed)``::

    AssertionError: snapshot drift in show-shown:
      --- show (recorded)
      +++ show (observed)
      @@ -1 +1 @@
      -shown:s1
      +SHOWN:s1

Revert the production edit; the target goes green again. That diff format is the
contract every tool's characterization is reviewed against.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .exerciser import ToolExerciser
from .snapshot import Snapshot

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"

# The structured-output tools return typed models, not the status string the
# corpus pins byte-for-byte. Their MCP output schema is derived from the result
# model, and their behavior is proven by the typed operation and adapter tests
# under tests/operations/, so they are not required to appear in this corpus.
STRUCTURED_TOOLS = frozenset(
    {
        "get_display_info",
        "get_theme",
        "get_window_settings",
        "inspect_scene",
        "list_clients",
        "list_errors",
        "list_menus",
        "list_recent_events",
        "list_scenes",
        "set_frame_state",
        "set_theme",
        "set_window_settings",
    }
)
# ``list_menus`` joined the structured set in the menu-ownership commit; the
# setters (``set_theme``, ``set_window_settings``, ``set_frame_state``) joined it
# when they were changed to return their write's own result model.


def _snapshot_files() -> list[Path]:
    return sorted(p for p in SNAPSHOT_DIR.glob("*.json"))


def _snapshot_ids() -> list[str]:
    return [p.stem for p in _snapshot_files()]


@pytest.mark.parametrize("path", _snapshot_files(), ids=_snapshot_ids())
def test_snapshot_replays(path: Path) -> None:
    snap = Snapshot.from_file(path)
    inputs = dict(snap.inputs)
    observed = ToolExerciser.call(snap.tool, inputs, snap.setup)
    assert snap.matches(observed), (
        f"snapshot drift in {path.stem}:\n{snap.describe_mismatch(observed)}"
    )


def test_corpus_is_non_empty() -> None:
    # If a future refactor accidentally deletes the corpus, the
    # parameterised test above would silently pass with zero items.
    # This test exists so "I forgot to regenerate the corpus" fails loud.
    assert _snapshot_files(), (
        "characterization corpus is empty — run "
        "`uv run --extra display python -m tests.characterization.build_corpus`"
    )


@pytest.mark.parametrize("path", _snapshot_files(), ids=_snapshot_ids())
def test_snapshot_has_no_absolute_paths(path: Path) -> None:
    """Snapshots must use REPO_ROOT_TOKEN, never a maintainer's host path.

    The corpus is checked into git and replays on every contributor's
    machine and on CI. An absolute path like ``/Users/foo/...`` or
    ``/home/foo/...`` would make the snapshot unreplayable elsewhere.
    """
    text = path.read_text(encoding="utf-8")
    for forbidden in ("/Users/", "/home/", "/private/var/"):
        assert forbidden not in text, (
            f"{path.name} contains absolute path token {forbidden!r}; "
            "use REPO_ROOT_TOKEN and run `make snapshot-record`"
        )


def test_every_tool_has_a_snapshot() -> None:
    """Every MCP tool registered in punt_lux.tools must appear in the corpus.

    The migration's safety net is only as good as its coverage. If a new
    tool is added without a snapshot, this test fails — the corpus is the
    contract for tool-level behavior across the migration.
    """
    from punt_lux import tools as tools_pkg

    non_tool_exports = {"mcp", "run_mcp_session"}
    registered = {
        name
        for name in tools_pkg.__all__
        if name not in non_tool_exports and name not in STRUCTURED_TOOLS
    }
    covered = {Snapshot.from_file(p).tool for p in _snapshot_files()}
    missing = sorted(registered - covered)
    assert not missing, (
        f"corpus missing snapshots for: {missing}. "
        "Add a scenario in tests/characterization/build_corpus.py and run "
        "`make snapshot-record`."
    )
