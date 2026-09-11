"""Coverage for ``CouplingRatchet._resolve_default_base_ref`` and the CLI's
bare ``--check`` default.

The regression this file guards: ``check-oo``'s own default already computes
``merge-base(origin/main, HEAD)`` (``GitRepo.resolve_base`` in
``tools/oo_ratchet/gitio.py``), so a bare local ``make check-oo`` already
scores the whole fork-to-HEAD range CI's ``pull_request`` trigger does.
``oo_coupling.py`` had no such default of its own -- its CLI fell straight
through to ``_git_touched_files``'s ``"HEAD~1"`` (last commit only) whenever
``--base-ref`` was omitted, which is exactly how a developer's ad-hoc
``make check-coupling`` (and the bare ``check-coupling`` target before this
fix) invokes it. A within-cap regression landed in an EARLIER commit of a
multi-commit local branch, never re-touched by a later commit, passed
locally and only ever failed once CI's explicit ``--base-ref`` (computed by
the workflow) caught it -- the green-locally/red-CI split this closes.

The fix gives the CLI itself the identical merge-base-aware default
``oo_score.py`` already has (``CouplingRatchet._resolve_default_base_ref``),
so a bare local invocation now scores the same range CI's ``pull_request``
trigger does, with no Makefile changes required on either target.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Self

import pytest

from tools.oo_coupling import CouplingRatchet, CouplingScorer

REPO_ROOT = Path(__file__).resolve().parents[2]
OO_COUPLING_SCRIPT = REPO_ROOT / "tools" / "oo_coupling.py"

# Same shape as tests/oo_coupling/test_push_base_ref.py's COHESIVE/DISJOINT
# pair: two methods sharing both attributes (max_lcom 0.0, cohesive) versus
# touching disjoint attributes (max_lcom 1.0, a real regression).
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
        self._b += 1

    def bump_b(self) -> None:
        self._a += 1
        self._b += 1
'''

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
    """An unrelated module touched by a later branch commit."""
    return 1
'''


class DefaultBaseRefFixture:
    """A throwaway git repo for exercising the CLI's bare ``--check`` default."""

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
        """Write ``.oo-coupling-baseline.json`` from the current scores."""
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

    def checkout_new(self, branch: str) -> None:
        subprocess.run(
            ["git", "checkout", "-q", "-b", branch],  # noqa: S607
            cwd=self._root,
            check=True,
        )

    def set_origin_main(self, sha: str) -> None:
        """Point ``refs/remotes/origin/main`` at ``sha``, as a real fetch would."""
        subprocess.run(
            ["git", "update-ref", "refs/remotes/origin/main", sha],  # noqa: S607
            cwd=self._root,
            check=True,
        )

    def merge_base(self, left: str, right: str) -> str:
        out = subprocess.run(
            ["git", "merge-base", left, right],  # noqa: S607
            cwd=self._root,
            check=True,
            capture_output=True,
            text=True,
        )
        return out.stdout.strip()

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
        return CouplingScorer(Path(subdir))

    def ratchet(self) -> CouplingRatchet:
        return CouplingRatchet(self._root)


@pytest.fixture
def fx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> DefaultBaseRefFixture:
    fixture = DefaultBaseRefFixture(tmp_path)
    # _resolve_default_base_ref and _git_touched_files run git with no
    # explicit cwd, so they must find this throwaway repo via the process
    # working directory -- same reason test_push_base_ref.py's fx does this.
    monkeypatch.chdir(fixture.root)
    return fixture


class TestResolveDefaultBaseRef:
    """The CLI-level default resolution, in isolation from ``check()``."""

    def test_resolves_merge_base_when_origin_main_is_fetched(
        self, fx: DefaultBaseRefFixture
    ) -> None:
        fx.write("sub/w.py", COHESIVE)
        fork = fx.commit("origin/main tip")
        fx.set_origin_main(fork)
        fx.checkout_new("feature")
        fx.write("sub/other.py", OTHER_MODULE)
        fx.commit("a feature commit")

        assert CouplingRatchet._resolve_default_base_ref() == fork

    def test_falls_back_to_head_tilde_1_when_unresolvable(
        self, fx: DefaultBaseRefFixture
    ) -> None:
        # No origin/main ref was ever set -- merge-base has nothing to
        # resolve against, so the old, narrower default is the safe fallback.
        fx.write("sub/w.py", COHESIVE)
        fx.commit("only commit, no origin/main")

        assert CouplingRatchet._resolve_default_base_ref() == "HEAD~1"

    def test_falls_back_to_head_tilde_1_when_merge_base_is_head(
        self, fx: DefaultBaseRefFixture
    ) -> None:
        # HEAD sits on origin/main with no commits ahead -- the shape of a
        # push whose origin/main was just fetched to the pushed tip
        # (ratchets.yml's bare `make check-coupling` on an all-zeros
        # github.event.before). merge-base(origin/main, HEAD) == HEAD, an
        # empty range; falling back to HEAD~1 scores the last commit instead
        # of vacuously passing.
        fx.write("sub/w.py", COHESIVE)
        fx.commit("first commit")
        fx.write("sub/other.py", OTHER_MODULE)
        tip = fx.commit("second commit -- the pushed tip")
        fx.set_origin_main(tip)

        assert CouplingRatchet._resolve_default_base_ref() == "HEAD~1"


class TestCliBareCheckDefault:
    """The real repro: the OLD default passes, the FIXED default fails.

    ``check(scorer, base_ref="HEAD~1")`` below is not a hypothetical old
    behavior -- it is the literal default ``main()`` used before this fix,
    reachable today by any caller (a test, a script) that never resolves a
    base ref at all, exactly as the CLI itself used to. The
    ``subprocess`` call is the real entry point ``make check-coupling``
    drives, with no ``--base-ref`` flag -- the exact invocation a
    developer's ad-hoc local run makes.
    """

    def test_bare_check_catches_a_regression_from_an_earlier_branch_commit(
        self, fx: DefaultBaseRefFixture
    ) -> None:
        # Fork point: cohesive, baselined -- what a real origin/main carries.
        fx.write("sub/w.py", COHESIVE)
        fx.snapshot("sub")
        fork = fx.commit("origin/main tip")
        fx.set_origin_main(fork)

        fx.checkout_new("feature")
        # First branch commit: w.py regresses. The in-tree baseline is NOT
        # updated, so the regression is real and detectable.
        fx.write("sub/w.py", DISJOINT)
        fx.commit("regress w.py (first commit of the branch)")
        # Second/last branch commit: an unrelated file. This is the commit
        # HEAD~1..HEAD -- the old default's range -- spans, and all it spans.
        fx.write("sub/other.py", OTHER_MODULE)
        fx.commit("add other.py (last commit of the branch)")

        # OLD: the literal pre-fix default, reachable via a direct caller
        # that supplies no base_ref -- only sees the last commit, misses the
        # regression buried in the first one.
        outcome_old = fx.ratchet().check(fx.scorer(), base_ref="HEAD~1")
        assert outcome_old == 0

        # FIXED: the real CLI entry point, invoked exactly as a bare local
        # `make check-coupling` invokes it -- no --base-ref at all. main()
        # now resolves merge-base(origin/main, HEAD) itself and catches it.
        result = subprocess.run(
            [sys.executable, str(OO_COUPLING_SCRIPT), "sub", "--check"],
            cwd=fx.root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 1, result.stdout + result.stderr
        assert "w.py" in result.stdout

    def test_bare_check_passes_when_the_branch_has_no_regression(
        self, fx: DefaultBaseRefFixture
    ) -> None:
        fx.write("sub/w.py", COHESIVE)
        fx.snapshot("sub")
        fork = fx.commit("origin/main tip")
        fx.set_origin_main(fork)

        fx.checkout_new("feature")
        fx.write("sub/other.py", OTHER_MODULE)
        fx.commit("add other.py (first commit of the branch)")
        fx.write("sub/other.py", OTHER_MODULE + "\n# a comment\n")
        fx.commit("touch other.py again (last commit of the branch)")

        result = subprocess.run(
            [sys.executable, str(OO_COUPLING_SCRIPT), "sub", "--check"],
            cwd=fx.root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
