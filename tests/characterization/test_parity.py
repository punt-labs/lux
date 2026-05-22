"""Snapshot parity test — every recorded snapshot replays identically.

This is the executable form of the characterization safety net introduced
in lux-edvm (PR 0). Every JSON file in ``tests/characterization/snapshots/``
is loaded as a :class:`Snapshot`, fed to :class:`ToolExerciser`, and the
live response is compared to the recorded response.

When a migration PR (lux-b14i and onward) is shipping correctly, this
test stays green. When a tool's wire-level output drifts — even by one
byte — the test fails with a unified diff showing exactly what changed.
``make snapshot-parity`` is the same assertion as a make target.

Manual regression check (the "negative case" the mission asks for): pick
any tool the corpus covers, deliberately break it by editing one
character in ``src/punt_lux/tools/tools.py`` (e.g., change ``"ack:"`` to
``"ACK:"`` in the ``show`` tool's success branch), then run::

    make snapshot-parity

The target exits non-zero. The pytest output names every failing
snapshot and embeds ``Snapshot.diff(observed)``::

    AssertionError: snapshot drift in show-ack:
      --- show (recorded)
      +++ show (observed)
      @@ -1 +1 @@
      -ack:s1
      +ACK:s1

Revert the production edit; the target goes green again. That diff
format is the contract the migration PRs (lux-b14i and onward) are
reviewed against.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from .exerciser import ToolExerciser
from .snapshot import Snapshot

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"


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
        f"snapshot drift in {path.stem}:\n{snap.diff(observed)}"
    )


def test_corpus_is_non_empty() -> None:
    # If a future refactor accidentally deletes the corpus, the
    # parameterised test above would silently pass with zero items.
    # This test exists so "I forgot to regenerate the corpus" fails loud.
    assert _snapshot_files(), (
        "characterization corpus is empty — run "
        "`uv run --extra display python -m tests.characterization.build_corpus`"
    )
