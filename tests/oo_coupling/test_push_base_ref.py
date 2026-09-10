"""Coverage for ``CouplingRatchet.check``'s ``base_ref`` parameter.

``_git_touched_files``/``_git_renamed_files`` run with no explicit ``cwd``
(they trust the process working directory to be the repo being scored, which
is how ``make check-coupling`` and the CI job invoke them) -- every test here
uses ``monkeypatch.chdir`` into a throwaway git repo so the tool's real git
subprocess calls land there instead of on this checkout.

The regression this file guards: on a push that lands more than one commit,
``check()``'s default ``base_ref="HEAD~1"`` only diffs the last commit. A
regression introduced in an *earlier* commit of the same push is invisible to
that range and passes trivially -- qodo's scenario 2 on lux PR #467. Passing
the push's pre-push tip of main as ``base_ref`` (what the CI job now does via
``PUSH_BASE_REF``/``github.event.before``) widens the diff to the whole push
range and catches it.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Self

import pytest

from tools.oo_coupling import CouplingRatchet, CouplingScorer

# Two methods sharing an attribute: LCOM (max_lcom) is 0.0 -- perfectly
# cohesive, the ratchet's "good" end.
COHESIVE = '''from __future__ import annotations


class Widget:
    """A widget with cohesive methods."""

    _a: int
    _b: int

    def __new__(cls) -> "Widget":
        self = super().__new__(cls)
        self._a = 0
        self._b = 0
        return self

    def bump_a(self) -> None:
        self._a += 1

    def bump_b(self) -> None:
        self._a += 1
'''

# Same shape, but the two methods now touch disjoint attributes: max_lcom
# regresses from 0.0 to 1.0 (the single method pair shares no self._* attrs).
DISJOINT = '''from __future__ import annotations


class Widget:
    """A widget with disjoint methods."""

    _a: int
    _b: int

    def __new__(cls) -> "Widget":
        self = super().__new__(cls)
        self._a = 0
        self._b = 0
        return self

    def bump_a(self) -> None:
        self._a += 1

    def bump_b(self) -> None:
        self._b += 1
'''

OTHER_MODULE = '''from __future__ import annotations


def helper() -> int:
    """An unrelated module touched by a later push commit."""
    return 1
'''


class CouplingGitFixture:
    """A throwaway git repo for exercising ``CouplingRatchet`` end to end."""

    _root: Path

    def __new__(cls, tmp: Path) -> Self:
        self = super().__new__(cls)
        subprocess.run(
            ["git", "init", "-q", "-b", "main"],  # noqa: S607
            cwd=tmp,
            check=True,
        )
        for key, val in (
            ("user.email", "t@example.com"),
            ("user.name", "Tester"),
            ("commit.gpgsign", "false"),
        ):
            subprocess.run(
                ["git", "config", key, val],  # noqa: S607
                cwd=tmp,
                check=True,
            )
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],  # noqa: S607
            cwd=tmp,
            check=True,
            capture_output=True,
            text=True,
        )
        self._root = Path(out.stdout.strip())
        return self

    @property
    def root(self) -> Path:
        """Return the repository root."""
        return self._root

    def write(self, rel: str, content: str) -> None:
        path = self._root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def snapshot(self, subdir: str = "sub") -> None:
        """Write ``.oo-coupling-baseline.json`` from the current scores.

        Scores ``Path(subdir)`` -- a path relative to the repo root, not
        ``self._root / subdir`` -- because ``git diff --name-only`` reports
        repo-relative paths and ``CouplingRatchet.check`` intersects them
        against the scorer's file keys verbatim (no path normalization). An
        absolute target here would score absolute keys that never match
        git's relative output, exactly like the production invocation
        (``python tools/oo_coupling.py src/punt_lux/ --check``) scores the
        relative ``src/punt_lux/`` from a cwd already at the repo root.
        """
        scorer = CouplingScorer(Path(subdir))
        results = CouplingRatchet._results_by_file(scorer.results)
        (self._root / CouplingRatchet.BASELINE_FILE).write_text(
            json.dumps(results, indent=2) + "\n"
        )

    def commit(self, msg: str) -> str:
        subprocess.run(["git", "add", "-A"], cwd=self._root, check=True)  # noqa: S607
        subprocess.run(
            ["git", "commit", "-q", "-m", msg],  # noqa: S607
            cwd=self._root,
            check=True,
        )
        return self._head()

    def _head(self) -> str:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            cwd=self._root,
            check=True,
            capture_output=True,
            text=True,
        )
        return out.stdout.strip()

    def scorer(self, subdir: str = "sub") -> CouplingScorer:
        # Relative to the repo root (cwd, via monkeypatch.chdir) -- see the
        # docstring on ``snapshot`` for why this must match git's relative
        # output rather than use an absolute path.
        return CouplingScorer(Path(subdir))

    def ratchet(self) -> CouplingRatchet:
        return CouplingRatchet(self._root)


@pytest.fixture
def fx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CouplingGitFixture:
    fixture = CouplingGitFixture(tmp_path)
    # _git_touched_files/_git_renamed_files run git with no explicit cwd, so
    # they must find this throwaway repo via the process working directory.
    monkeypatch.chdir(fixture.root)
    return fixture


class TestMultiCommitPushBaseRef:
    """A multi-commit push must be diffed as a whole range, not one commit."""

    def test_default_base_ref_misses_earlier_commit_regression(
        self, fx: CouplingGitFixture
    ) -> None:
        # Commit 1: the pre-push tip of main -- cohesive, baselined.
        fx.write("sub/w.py", COHESIVE)
        fx.snapshot("sub")
        before = fx.commit("pre-push main tip")

        # Commit 2 (first commit of the push): w.py regresses to disjoint
        # methods. The in-tree baseline is NOT updated, so the regression is
        # real and detectable -- current (1.0) vs baseline (0.0).
        fx.write("sub/w.py", DISJOINT)
        fx.commit("regress w.py (first commit of the push)")

        # Commit 3 (second/last commit of the push): an unrelated file is
        # added. This is the commit HEAD~1..HEAD spans.
        fx.write("sub/other.py", OTHER_MODULE)
        fx.commit("add other.py (last commit of the push)")

        # Old buggy behavior: default base_ref="HEAD~1" only sees commit 3.
        # w.py's regression from commit 2 is invisible to that range.
        outcome_default = fx.ratchet().check(fx.scorer(), base_ref="HEAD~1")
        assert outcome_default == 0

        # Fixed behavior: base_ref=<pre-push tip> diffs the whole push range
        # (before..HEAD) and catches the regression buried in commit 2.
        outcome_push = fx.ratchet().check(fx.scorer(), base_ref=before)
        assert outcome_push == 1

    def test_push_base_ref_passes_when_push_has_no_regression(
        self, fx: CouplingGitFixture
    ) -> None:
        fx.write("sub/w.py", COHESIVE)
        fx.snapshot("sub")
        before = fx.commit("pre-push main tip")

        fx.write("sub/other.py", OTHER_MODULE)
        fx.commit("add other.py (first commit of the push)")
        fx.write("sub/other.py", OTHER_MODULE + "\n# a comment\n")
        fx.commit("touch other.py again (last commit of the push)")

        outcome = fx.ratchet().check(fx.scorer(), base_ref=before)
        assert outcome == 0
