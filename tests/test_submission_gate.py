"""Unit tests for the pre-install SubmissionGate facade.

The gate composes per-element self-validation with tree-level id uniqueness
and returns the first agent-facing rejection reason, or ``None`` for a clean
tree that may be installed.
"""

from __future__ import annotations

from punt_lux.domain.ids import SceneId
from punt_lux.domain.submission_gate import SubmissionGate
from punt_lux.protocol.elements import GroupElement, ProgressElement, TextElement

_SCENE = SceneId("submission-gate-scene")


class TestSubmissionGate:
    def test_clean_tree_has_no_rejection(self) -> None:
        roots = [
            TextElement(id="a", content="one"),
            GroupElement(
                id="g", layout="rows", children=(TextElement(id="b", content="two"),)
            ),
        ]
        assert SubmissionGate().first_rejection(_SCENE, roots) is None

    def test_self_validation_failure_is_reported(self) -> None:
        roots = [ProgressElement(id="p", fraction=-0.5)]
        rejection = SubmissionGate().first_rejection(_SCENE, roots)
        assert rejection is not None
        assert "[progress 'p']" in rejection

    def test_duplicate_id_is_reported(self) -> None:
        roots = [
            TextElement(id="dup", content="root"),
            GroupElement(
                id="g",
                layout="rows",
                children=(TextElement(id="dup", content="child"),),
            ),
        ]
        rejection = SubmissionGate().first_rejection(_SCENE, roots)
        assert rejection is not None
        assert "duplicate element id 'dup'" in rejection
        assert "unique" in rejection

    def test_self_validation_precedes_duplicate_check(self) -> None:
        roots = [
            ProgressElement(id="dup", fraction=2.0),
            TextElement(id="dup", content="child"),
        ]
        rejection = SubmissionGate().first_rejection(_SCENE, roots)
        assert rejection is not None
        assert "[progress 'dup']" in rejection
