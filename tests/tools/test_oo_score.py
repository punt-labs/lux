"""Regression tests for the OO ratchet's git touched-file window (lux-83ig).

``tools/oo_score.py --check`` decides which files count as "touched" by
diffing against git. Before round 1, that diff was ``HEAD~1..HEAD`` — only
the LAST commit. On a multi-commit branch that hides an earlier commit's
regression whenever the branch's final commit doesn't touch the regressed
file (e.g. a closing docs commit) — exactly what happened before PR #446
squash-merged ~10 regressed files onto ``main``. Round 1's fix windows
against the merge-base with the target branch, matching what a squash-merge
actually lands: the WHOLE branch diff, not one commit.

Round 2 hardens the seam between that window and the scorer: ``select()``
is the sole public entry point on ``GitDiffWindow``, normalizes both sides
to absolute paths before intersecting (so an absolute or subdirectory
invocation still matches git's repo-root-relative diff), and fails safe to
the FULL scored set — never the empty one — whenever the window itself
can't be resolved.

Every environment-sensitive fixture here runs git through an isolated
environment (``_isolated_git_env``): a private ``HOME`` and both config layers
pointed at ``/dev/null``, so a global gitconfig, credential helper, commit
template, or non-``main`` ``init.defaultBranch`` on the host can never leak
into what these tests observe. Branch names are always passed explicitly to
``git init -b`` for the same reason.

These tests build real git repos in a ``tmp_path`` and run the actual
script as a subprocess — a git boundary this sensitive is worth exercising
for real rather than mocking.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_OO_SCORE = _REPO_ROOT / "tools" / "oo_score.py"
_GIT = shutil.which("git") or "git"

_AUTHOR_NAME = "OO Ratchet Test"
_AUTHOR_EMAIL = "rmh@punt-labs.test"


def _isolated_git_env(home: Path) -> dict[str, str]:
    """A git environment insulated from this machine's global/system config.

    Global config leakage — a stray credential helper, a commit template,
    a non-``main`` ``init.defaultBranch``, an interactive gpg-signing
    default — is the leading suspect for the "fails on the session's
    first git invocation, passes on every later one" flake both round-1
    reviewers observed and neither could pin to a code defect: a config
    read once and then cached (by git, by gpg-agent, by the OS) only bites
    cold. Pointing both config layers at ``/dev/null`` and giving git a
    scratch ``HOME`` removes the whole class of cause regardless of which
    exact setting it turns out to be, rather than guessing at one.
    """
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_AUTHOR_NAME": _AUTHOR_NAME,
        "GIT_AUTHOR_EMAIL": _AUTHOR_EMAIL,
        "GIT_COMMITTER_NAME": _AUTHOR_NAME,
        "GIT_COMMITTER_EMAIL": _AUTHOR_EMAIL,
    }


_BASELINE_MODULE = '''"""Fixture module for the ratchet touched-file window test."""

from __future__ import annotations


class Widget:
    """A small widget with one bump method."""

    def __new__(cls) -> Widget:
        self = super().__new__(cls)
        self._value = 0
        return self

    def bump(self) -> None:
        self._value += 1
'''

# Twenty trivial extra methods — enough non-blank lines to regress
# ``module_size`` against the committed baseline regardless of its absolute
# value, without disturbing any other metric (each method is one param,
# complexity 1, and still a method — method_ratio stays at 1.0).
_EXTRA_METHODS = "".join(
    f"\n    def bump_{i}(self) -> None:\n        self._value += 1\n" for i in range(20)
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        [_GIT, *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        env=_isolated_git_env(repo),
    )


def _run_check_oo(
    repo: Path, target: str, *flags: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_OO_SCORE), target, *flags],
        cwd=repo,
        capture_output=True,
        text=True,
        env=_isolated_git_env(repo),
    )


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)


def _probe(repo: Path, scored: set[str]) -> subprocess.CompletedProcess[str]:
    """Run ``GitDiffWindow(repo).select(scored)`` in a subprocess and return it.

    ``tools/`` is a standalone-script directory, not a package on the
    type-checked source path, so importing it directly into this test
    process would need an unresolvable-import suppression this test has no
    business asking for.
    """
    code = (
        f"import sys; sys.path.insert(0, {str(_OO_SCORE.parent)!r}); "
        f"from pathlib import Path; import oo_score; "
        f"print(sorted(oo_score.GitDiffWindow(Path({str(repo)!r})).select({scored!r})))"
    )
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
        env=_isolated_git_env(repo),
    )


def _init_repo_with_committed_baseline(tmp_path: Path) -> Path:
    """A one-commit ``main`` carrying ``pkg/mod.py`` and its OO baseline."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", _AUTHOR_EMAIL)
    _git(repo, "config", "user.name", _AUTHOR_NAME)

    pkg = repo / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "mod.py").write_text(_BASELINE_MODULE)

    update = _run_check_oo(repo, "pkg", "--update")
    assert update.returncode == 0, update.stdout + update.stderr

    _commit_all(repo, "commit A: baseline")
    return repo


def test_regression_hidden_by_docs_only_final_commit_is_caught(tmp_path: Path) -> None:
    """The whole-branch diff catches a regression an earlier commit left.

    Commit 1 regresses ``module_size`` on ``pkg/mod.py``. Commit 2 touches
    ONLY a markdown file. A ``HEAD~1..HEAD`` window sees just commit 2's
    diff — no Python files — and trivially passes, exactly the bug this
    fix closes. The merge-base window sees both commits and must fail.
    """
    repo = _init_repo_with_committed_baseline(tmp_path)
    _git(repo, "checkout", "-b", "feature")

    (repo / "pkg" / "mod.py").write_text(_BASELINE_MODULE + _EXTRA_METHODS)
    _commit_all(repo, "commit 1: regress module_size")

    (repo / "docs").mkdir()
    (repo / "docs" / "note.md").write_text("# Note\n")
    _commit_all(repo, "commit 2: docs only, no Python touched")

    result = _run_check_oo(repo, "pkg", "--check")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "module_size" in result.stdout
    assert "REGRESSED" in result.stdout


def test_branch_with_no_regression_still_passes(tmp_path: Path) -> None:
    """Widening the window must not manufacture false failures.

    Commit 1 touches the Python file with a real, IMPROVING metric move —
    dropping the class docstring shrinks ``module_size`` by one line —
    never a wording-only edit that leaves every metric untouched. Commit
    2, like the failing case above, touches only a markdown file. The
    whole branch diff includes the Python touch, so the file must actually
    show up in the ``--check`` output: asserting only the exit code would
    also pass if the widened window silently missed the file entirely,
    which is exactly the gap this assertion closes.
    """
    repo = _init_repo_with_committed_baseline(tmp_path)
    _git(repo, "checkout", "-b", "feature")

    improved = _BASELINE_MODULE.replace(
        '    """A small widget with one bump method."""\n', ""
    )
    (repo / "pkg" / "mod.py").write_text(improved)
    _commit_all(repo, "commit 1: drop docstring, module_size improves")

    (repo / "docs").mkdir()
    (repo / "docs" / "note.md").write_text("# Note\n")
    _commit_all(repo, "commit 2: docs only, no Python touched")

    result = _run_check_oo(repo, "pkg", "--check")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "pkg/mod.py" in result.stdout
    assert "module_size" in result.stdout
    assert "IMPROVED" in result.stdout


def test_head_equals_target_scores_the_parent_diff(tmp_path: Path) -> None:
    """A regression committed directly to ``main`` is still caught.

    No feature branch exists to diff against a merge-base — HEAD IS the
    target ref. ``GitDiffWindow`` falls back to the single-parent window
    (``HEAD~1..HEAD``) there, which is the whole landed change under this
    repo's squash-merge-plus-``make-check``-before-every-commit workflow
    (see the comment on this branch in ``GitDiffWindow._resolve_window``).
    """
    repo = _init_repo_with_committed_baseline(tmp_path)

    (repo / "pkg" / "mod.py").write_text(_BASELINE_MODULE + _EXTRA_METHODS)
    _commit_all(repo, "regress module_size directly on main")

    result = _run_check_oo(repo, "pkg", "--check")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "module_size" in result.stdout
    assert "REGRESSED" in result.stdout


def test_none_window_fails_safe_and_still_catches_a_regression(tmp_path: Path) -> None:
    """--check must still catch a regression when the git window can't resolve.

    No target ref exists — the branch is named ``solo``, not ``main`` or
    ``origin/main`` — so ``GitDiffWindow.select()`` takes its unresolvable-
    window fail-safe path and returns the FULL scored set rather than
    treating "no window" as "nothing touched". This is the end-to-end
    proof of the fail-safe's actual purpose: a regression is caught, not
    silently waved through, when git can't scope the diff at all —
    exercising it through ``select()``'s sentinel alone would prove the
    signal fires but not that anything downstream honors it.
    """
    repo = tmp_path / "lonely"
    repo.mkdir()
    _git(repo, "init", "-b", "solo")
    _git(repo, "config", "user.email", _AUTHOR_EMAIL)
    _git(repo, "config", "user.name", _AUTHOR_NAME)

    pkg = repo / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "mod.py").write_text(_BASELINE_MODULE)

    update = _run_check_oo(repo, "pkg", "--update")
    assert update.returncode == 0, update.stdout + update.stderr
    _commit_all(repo, "solo baseline")

    (repo / "pkg" / "mod.py").write_text(_BASELINE_MODULE + _EXTRA_METHODS)
    _commit_all(repo, "regress module_size, no resolvable target ref")

    result = _run_check_oo(repo, "pkg", "--check")

    assert result.returncode == 1, result.stdout + result.stderr
    assert "pkg/mod.py" in result.stdout
    assert "module_size" in result.stdout
    assert "REGRESSED" in result.stdout


def test_select_fails_safe_to_full_scored_set_when_no_target_ref_is_resolvable(
    tmp_path: Path,
) -> None:
    """No local ``main`` and no ``origin`` remote: ``select()`` must not fail open.

    ``select()`` must return the full ``scored`` set (compare every scored
    file against baseline) rather than the empty set — an empty set is
    exactly the false "nothing touched" signal this whole bug class is
    about.
    """
    repo = tmp_path / "lonely"
    repo.mkdir()
    _git(repo, "init", "-b", "trunk")  # deliberately not "main"
    _git(repo, "config", "user.email", _AUTHOR_EMAIL)
    _git(repo, "config", "user.name", _AUTHOR_NAME)
    (repo / "a.py").write_text("x = 1\n")
    _commit_all(repo, "only commit")

    result = _probe(repo, {"a.py", "b.py"})

    assert result.stdout.strip() == "['a.py', 'b.py']"


def test_select_fails_safe_when_head_and_target_share_no_history(
    tmp_path: Path,
) -> None:
    """An orphan branch has no merge-base with ``main`` — ``select()`` fails safe.

    ``git merge-base`` returns nothing when HEAD and the target ref share
    no common ancestor. That is a genuine "can't resolve a window" case,
    not a "nothing touched" one, so ``select()`` must return the full
    scored set rather than the empty one.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", _AUTHOR_EMAIL)
    _git(repo, "config", "user.name", _AUTHOR_NAME)
    (repo / "a.py").write_text("x = 1\n")
    _commit_all(repo, "main commit")

    _git(repo, "checkout", "--orphan", "unrelated")
    _git(repo, "rm", "-rf", "-q", ".")
    (repo / "b.py").write_text("y = 2\n")
    _commit_all(repo, "orphan commit, no shared history with main")

    result = _probe(repo, {"a.py", "b.py"})

    assert result.stdout.strip() == "['a.py', 'b.py']"


def test_branch_diff_entirely_outside_scored_subtree_trivially_passes(
    tmp_path: Path,
) -> None:
    """A branch whose whole diff lies outside the scored subtree must pass.

    Round 1 briefly carried a "fail-unsafe" heuristic: any non-empty
    window with an empty scored intersection fell back to scoring the
    FULL tree, on the theory that an empty intersection was suspicious.
    Evaluator gvr independently reproduced that this repo's own
    ``make check-oo`` goes red under that heuristic -- every out-of-scope
    PR (tools/tests/docs-only) becomes a spurious full-tree regression
    report -- and confirmed reverting it is correct. This test pins the
    revert: the branch here touches only ``other/unrelated.py``, entirely
    outside the ``pkg`` subtree being checked, so the resolved window's
    intersection with ``pkg``'s scored files is genuinely empty, and
    ``--check pkg`` must trivially pass rather than fall back to scoring
    every file in ``pkg`` against the baseline.
    """
    repo = _init_repo_with_committed_baseline(tmp_path)
    _git(repo, "checkout", "-b", "feature")

    (repo / "other").mkdir()
    (repo / "other" / "unrelated.py").write_text("x = 1\n")
    _commit_all(repo, "touch a file entirely outside pkg/")

    result = _run_check_oo(repo, "pkg", "--check")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "No Python files touched -- trivial pass" in result.stdout


def test_check_from_subdirectory_with_relative_target_still_catches_regression(
    tmp_path: Path,
) -> None:
    """A --check run from inside the scored directory still catches a regression.

    ``git diff --name-only`` always reports repo-root-relative paths
    (``pkg/mod.py``) no matter what ``cwd`` the diff is run from. But when
    ``--check`` itself is invoked with ``cwd=pkg`` and a relative target
    of ``.``, the scorer's own touched-file keys come out relative to
    THAT cwd -- ``mod.py``, not ``pkg/mod.py``. Before ``_normalize``,
    ``GitDiffWindow._select`` intersected these two path spaces directly
    and the intersection was always empty for a subdirectory invocation,
    silently trivial-passing every regression underneath it. This is the
    exact seam ``_normalize`` exists to close: both sides resolve to the
    same absolute path (scored anchored at ``Path.cwd()``, git's output
    anchored at the repo root), so the intersection is non-empty and the
    regression is caught. A relative (not absolute) target keeps this
    test clear of the separate, pre-existing Ratchet baseline-key bug
    that an absolute-target invocation would trip (raw-string baseline
    keys, tracked as a follow-up).
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", _AUTHOR_EMAIL)
    _git(repo, "config", "user.name", _AUTHOR_NAME)

    pkg = repo / "pkg"
    pkg.mkdir()
    (pkg / "mod.py").write_text(_BASELINE_MODULE)

    # --update runs with cwd=pkg and target="." -- the baseline is keyed
    # "mod.py" (no "pkg/" prefix) and lives at pkg/.oo-baseline.json.
    update = subprocess.run(
        [sys.executable, str(_OO_SCORE), ".", "--update"],
        cwd=pkg,
        capture_output=True,
        text=True,
        env=_isolated_git_env(repo),
    )
    assert update.returncode == 0, update.stdout + update.stderr
    _commit_all(repo, "commit A: baseline")

    _git(repo, "checkout", "-b", "feature")
    (pkg / "mod.py").write_text(_BASELINE_MODULE + _EXTRA_METHODS)
    _commit_all(repo, "commit 1: regress module_size")

    result = subprocess.run(
        [sys.executable, str(_OO_SCORE), ".", "--check"],
        cwd=pkg,
        capture_output=True,
        text=True,
        env=_isolated_git_env(repo),
    )

    assert result.returncode == 1, result.stdout + result.stderr
    assert "module_size" in result.stdout
    assert "REGRESSED" in result.stdout


def test_select_fails_safe_when_git_is_unavailable(tmp_path: Path) -> None:
    """``git`` missing from ``PATH`` must fail safe, not crash.

    ``FileNotFoundError`` is an ``OSError`` subclass; ``select()``'s
    boundary catch must cover it so a git-less environment scores
    everything rather than raising.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", _AUTHOR_EMAIL)
    _git(repo, "config", "user.name", _AUTHOR_NAME)
    (repo / "a.py").write_text("x = 1\n")
    _commit_all(repo, "only commit")

    code = (
        f"import sys; sys.path.insert(0, {str(_OO_SCORE.parent)!r}); "
        f"from pathlib import Path; import oo_score; "
        f"print(sorted(oo_score.GitDiffWindow(Path({str(repo)!r})).select({{'a.py'}})))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        check=True,
        env={"PATH": ""},
    )

    assert result.stdout.strip() == "['a.py']"


def test_diagnose_marks_score_everything_fallback_on_unresolvable_window(
    tmp_path: Path,
) -> None:
    """The stderr diagnostic must name the fallback when the window fails.

    ``select()``'s fail-safe path is silent to stdout by design -- a
    passing ``--check`` looks identical whether it resolved a real window
    or fell back to scoring everything. The stderr diagnostic is the only
    place that distinction is visible, and it must say so explicitly.
    """
    repo = tmp_path / "lonely"
    repo.mkdir()
    _git(repo, "init", "-b", "trunk")  # not "main"/"origin/main" -- unresolvable
    _git(repo, "config", "user.email", _AUTHOR_EMAIL)
    _git(repo, "config", "user.name", _AUTHOR_NAME)
    (repo / "a.py").write_text("x = 1\n")
    _commit_all(repo, "only commit")

    result = _probe(repo, {"a.py"})

    assert "SCORE-EVERYTHING FALLBACK" in result.stderr


def test_diagnose_omits_fallback_marker_on_a_resolved_window(tmp_path: Path) -> None:
    """A resolved window's diagnostic must not claim the fallback fired.

    The counterpart to the fallback-marker test above: a window that DID
    resolve against a real merge-base must not carry the same "score
    everything" note, or the marker would be meaningless noise on every
    run rather than a genuine signal of the unresolvable-window path.
    """
    repo = _init_repo_with_committed_baseline(tmp_path)
    _git(repo, "checkout", "-b", "feature")
    (repo / "pkg" / "mod.py").write_text(_BASELINE_MODULE + _EXTRA_METHODS)
    _commit_all(repo, "regress module_size")

    result = _probe(repo, {"pkg/mod.py"})

    assert "SCORE-EVERYTHING FALLBACK" not in result.stderr


def test_prefers_origin_main_over_stale_local_main_as_merge_base_target(
    tmp_path: Path,
) -> None:
    """A stale local ``main`` must not widen the window past ``origin/main``.

    GitHub's PR diff is ``origin/main...HEAD``, so the remote-tracking ref is
    the faithful merge target. When local ``main`` lags behind ``origin/main``,
    ``git merge-base main HEAD`` sits too far back and pulls unrelated upstream
    commits into the window -- an upstream-only regression then gets wrongly
    attributed to the feature branch. ``origin/main`` is preferred so the
    window is the branch's real divergence point.

    ``origin/main`` here carries a ``module_size`` regression on
    ``pkg/mod.py`` (upstream commit B); local ``main`` is left pointing at the
    healthy baseline (commit A). The feature branch forks from ``origin/main``
    and adds only a healthy, in-scope module (``pkg/extra.py``). Windowing
    against ``origin/main`` (=B) sees just that healthy addition and passes;
    windowing against stale local ``main`` (=A) would drag the upstream
    regression in and fail. Passing proves the remote-tracking target won.
    """
    repo = _init_repo_with_committed_baseline(tmp_path)

    origin = tmp_path / "origin.git"
    _git(repo, "init", "--bare", str(origin))
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "origin", "main")

    # Advance origin/main with an upstream regression, leaving local main at A.
    _git(repo, "checkout", "-b", "upstream")
    (repo / "pkg" / "mod.py").write_text(_BASELINE_MODULE + _EXTRA_METHODS)
    _commit_all(repo, "upstream commit B: regress module_size")
    _git(repo, "push", "origin", "upstream:main")
    _git(repo, "fetch", "origin")

    # Fork the feature from the up-to-date origin/main and add a healthy,
    # in-scope module. Local main is still the stale baseline (commit A).
    _git(repo, "checkout", "-b", "feature", "origin/main")
    (repo / "pkg" / "extra.py").write_text(_BASELINE_MODULE.replace("Widget", "Gadget"))
    _commit_all(repo, "feature commit C: add a healthy in-scope module")

    result = _run_check_oo(repo, "pkg", "--check")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "pkg/extra.py" in result.stdout
    assert "pkg/mod.py" not in result.stdout
    assert "REGRESSED" not in result.stdout


def test_check_scores_new_baseline_absent_file_against_absolute_thresholds(
    tmp_path: Path,
) -> None:
    """A touched .py file with no baseline entry is scored as NEW.

    The touched-file rework changed which files even reach ``check()``'s
    per-file loop, so the NEW-file branch (a touched file the baseline has
    never seen) needs its own coverage here: a second module added on the
    feature branch, with the same healthy shape as the baseline fixture,
    must show up as a NEW row graded against ``Scorer.THRESHOLDS``
    directly -- there is no baseline entry to diff it against.
    """
    repo = _init_repo_with_committed_baseline(tmp_path)
    _git(repo, "checkout", "-b", "feature")

    (repo / "pkg" / "extra.py").write_text(_BASELINE_MODULE.replace("Widget", "Gadget"))
    _commit_all(repo, "add a second module absent from the baseline")

    result = _run_check_oo(repo, "pkg", "--check")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "pkg/extra.py" in result.stdout
    assert "NEW" in result.stdout
