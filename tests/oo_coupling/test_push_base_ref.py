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
``BASE_REF``/``github.event.before``) widens the diff to the whole push
range and catches it.

``TestMultiCommitPrBaseRef`` below guards the same hole on the OTHER trigger:
a multi-commit PULL REQUEST, where ``HEAD~1..HEAD`` only ever sees the last
commit of the PR, not the whole PR range since it forked from ``origin/main``
(Copilot finding on PR #467, round 2). The fix there is
``merge-base(origin/main, HEAD)`` -- the PR's fork point -- passed the same
way as the push case: ``make check-coupling BASE_REF=<merge-base-sha>``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Self

import pytest

from tools.oo_coupling import CouplingRatchet, CouplingScorer

# Two methods, each touching both attributes: LCOM (max_lcom) is 0.0 --
# perfectly cohesive, the ratchet's "good" end. Both methods touch both
# ``_a`` and ``_b`` (rather than ``bump_b`` quietly touching only ``_a``) so
# the method names match what they do -- cohesion still holds because their
# attribute sets always intersect.
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

    def checkout_new(self, branch: str) -> None:
        subprocess.run(
            ["git", "checkout", "-q", "-b", branch],  # noqa: S607
            cwd=self._root,
            check=True,
        )

    def checkout(self, branch: str) -> None:
        subprocess.run(
            ["git", "checkout", "-q", branch],  # noqa: S607
            cwd=self._root,
            check=True,
        )

    def set_origin_main(self, sha: str) -> None:
        """Point ``refs/remotes/origin/main`` at ``sha``, as a real fetch would.

        Mirrors ``GitFixture.set_origin_main`` in
        ``tests/oo_ratchet/test_oo_ratchet.py`` -- a real remote-tracking ref,
        not a same-named local branch, so ``git merge-base origin/main HEAD``
        resolves exactly the way the CI checkout's ``origin/main`` does.
        """
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


class TestMultiCommitPrBaseRef:
    """A multi-commit PULL REQUEST must be diffed as the whole PR range too.

    Same hole as ``TestMultiCommitPushBaseRef`` above, on the other CI
    trigger: ``check()``'s default ``base_ref="HEAD~1"`` sees only the PR's
    LAST commit. A regression introduced in the PR's FIRST commit, never
    re-touched by a later commit, passed trivially before this fix (Copilot
    finding on lux PR #467, round 2 -- filed after the push-side fix above
    had already landed). ``ratchets.yml``'s pull_request job now computes
    ``merge-base(origin/main, HEAD)`` -- the PR's fork point -- once, and
    passes it the same way the push job passes ``github.event.before``.
    """

    def test_default_base_ref_misses_earlier_pr_commit_regression(
        self, fx: CouplingGitFixture
    ) -> None:
        # origin/main tip: cohesive, baselined -- this is the PR's fork point.
        fx.write("sub/w.py", COHESIVE)
        fx.snapshot("sub")
        fork = fx.commit("origin/main tip")
        fx.set_origin_main(fork)

        fx.checkout_new("feature")
        # First commit of the PR: w.py regresses. The in-tree baseline is NOT
        # updated, so the regression is real and detectable.
        fx.write("sub/w.py", DISJOINT)
        fx.commit("regress w.py (first commit of the PR)")

        # Last commit of the PR: an unrelated file. This is the commit
        # HEAD~1..HEAD spans -- and all it spans.
        fx.write("sub/other.py", OTHER_MODULE)
        fx.commit("add other.py (last commit of the PR)")

        # Old buggy behavior: default base_ref="HEAD~1" only sees the last
        # commit. w.py's regression from the first commit is invisible to it.
        outcome_default = fx.ratchet().check(fx.scorer(), base_ref="HEAD~1")
        assert outcome_default == 0

        # Fixed behavior: base_ref=merge-base(origin/main, HEAD) diffs the
        # whole PR range (fork..HEAD) and catches the regression.
        merge_base = fx.merge_base("origin/main", "HEAD")
        outcome_pr = fx.ratchet().check(fx.scorer(), base_ref=merge_base)
        assert outcome_pr == 1

    def test_merge_base_passes_when_pr_has_no_regression(
        self, fx: CouplingGitFixture
    ) -> None:
        fx.write("sub/w.py", COHESIVE)
        fx.snapshot("sub")
        fork = fx.commit("origin/main tip")
        fx.set_origin_main(fork)

        fx.checkout_new("feature")
        fx.write("sub/other.py", OTHER_MODULE)
        fx.commit("add other.py (first commit of the PR)")
        fx.write("sub/other.py", OTHER_MODULE + "\n# a comment\n")
        fx.commit("touch other.py again (last commit of the PR)")

        merge_base = fx.merge_base("origin/main", "HEAD")
        outcome = fx.ratchet().check(fx.scorer(), base_ref=merge_base)
        assert outcome == 0

    def test_merge_base_excludes_concurrent_main_regression(
        self, fx: CouplingGitFixture
    ) -> None:
        """A regression landed on main by someone else's PR is out of scope."""
        fx.write("sub/w.py", COHESIVE)
        fx.snapshot("sub")
        fork = fx.commit("origin/main tip")
        fx.set_origin_main(fork)

        fx.checkout_new("feature")
        fx.write("sub/other.py", OTHER_MODULE)
        fx.commit("unrelated PR change")

        # Main advances concurrently, on a different local branch, with a
        # regression this PR never touched -- the fetched origin/main ref
        # moves to that new tip, but merge-base(origin/main, feature) is
        # still the fork point, so the regression stays out of this PR's
        # touched-file diff.
        fx.checkout("main")
        fx.write("sub/w.py", DISJOINT)
        main_head = fx.commit("regress w.py on main, concurrently with the PR")
        fx.set_origin_main(main_head)
        fx.checkout("feature")

        merge_base = fx.merge_base("origin/main", "HEAD")
        outcome = fx.ratchet().check(fx.scorer(), base_ref=merge_base)
        assert outcome == 0


class TestRenamedFiles:
    """``_git_renamed_files`` must exclude only *pure* (byte-identical) renames.

    ``git diff --diff-filter=R`` matches any rename git detects, including one
    where the content also changed (e.g. ``R82`` -- 82% similar, not 100%).
    Treating every ``R*`` match as a no-op rename would subtract a genuinely
    modified file from ``touched`` right alongside a true no-op rename --
    exactly the file most in need of scoring, silently dropped.
    """

    def test_pure_rename_is_excluded(self, fx: CouplingGitFixture) -> None:
        fx.write("sub/w.py", COHESIVE)
        before = fx.commit("add w.py")

        (fx.root / "sub" / "w.py").unlink()
        fx.write("sub/w_renamed.py", COHESIVE)
        fx.commit("pure rename, byte-identical content")

        assert CouplingRatchet._git_renamed_files(before) == {"sub/w_renamed.py"}

    def test_rename_with_content_change_is_not_excluded(
        self, fx: CouplingGitFixture
    ) -> None:
        fx.write("sub/w.py", COHESIVE)
        before = fx.commit("add w.py")

        (fx.root / "sub" / "w.py").unlink()
        fx.write("sub/w_renamed.py", DISJOINT)
        fx.commit("rename and regress w.py -> w_renamed.py")

        # Git still pairs this as a rename (content is well over the 50%
        # similarity default), but it is not a *pure* one -- the new path
        # must stay eligible for scoring, not be silently dropped.
        assert CouplingRatchet._git_renamed_files(before) == set()

    def test_check_still_scores_renamed_and_modified_file(
        self, fx: CouplingGitFixture, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """End to end: a rename-with-regression stays visible through ``check()``.

        A rename always changes the path, so the baseline -- keyed by the old
        path -- can never have an entry under the new one; this can't surface
        as an exit-code FAIL from a single push. What the fix guarantees is
        that the file is still scored and reported (as NEW), rather than
        vanishing from ``touched`` the way a pure rename correctly does (see
        ``test_check_drops_pure_rename_entirely`` below for the contrast).
        """
        fx.write("sub/w.py", COHESIVE)
        fx.snapshot("sub")
        before = fx.commit("pre-push main tip")

        (fx.root / "sub" / "w.py").unlink()
        fx.write("sub/w_renamed.py", DISJOINT)
        fx.commit("rename and regress w.py -> w_renamed.py")

        outcome = fx.ratchet().check(fx.scorer(), base_ref=before)
        assert outcome == 0  # no baseline entry under the new path -> INFO
        out = capsys.readouterr().out
        assert "sub/w_renamed.py" in out
        assert "NEW" in out

    def test_check_drops_pure_rename_entirely(
        self, fx: CouplingGitFixture, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fx.write("sub/w.py", COHESIVE)
        fx.snapshot("sub")
        before = fx.commit("pre-push main tip")

        (fx.root / "sub" / "w.py").unlink()
        fx.write("sub/w_renamed.py", COHESIVE)
        fx.commit("pure rename, no content change")

        outcome = fx.ratchet().check(fx.scorer(), base_ref=before)
        assert outcome == 0
        out = capsys.readouterr().out
        assert "No Python files touched -- trivial pass" in out
