"""Regression tests for the OO ratchet's git touched-file window (lux-83ig).

``tools/oo_score.py --check`` decides which files count as "touched" by
diffing against git. Before this fix, that diff was ``HEAD~1..HEAD`` — only
the LAST commit. On a multi-commit branch that hides an earlier commit's
regression whenever the branch's final commit doesn't touch the regressed
file (e.g. a closing docs commit) — exactly what happened before PR #446
squash-merged ~10 regressed files onto ``main``. The fix windows against the
merge-base with the target branch, matching what a squash-merge actually
lands: the WHOLE branch diff, not one commit.

These tests build a real two-commit git branch in a ``tmp_path`` repo and
run the actual script as a subprocess — a git boundary this sensitive is
worth exercising for real rather than mocking.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_OO_SCORE = _REPO_ROOT / "tools" / "oo_score.py"
_GIT = shutil.which("git") or "git"

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
    subprocess.run([_GIT, *args], cwd=repo, capture_output=True, text=True, check=True)


def _run_check_oo(
    repo: Path, target: str, *flags: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_OO_SCORE), target, *flags],
        cwd=repo,
        capture_output=True,
        text=True,
    )


def _commit_all(repo: Path, message: str) -> None:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", message)


def _init_repo_with_committed_baseline(tmp_path: Path) -> Path:
    """A one-commit ``main`` carrying ``pkg/mod.py`` and its OO baseline."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "rmh@punt-labs.test")
    _git(repo, "config", "user.name", "OO Ratchet Test")

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

    Commit 1 touches the Python file without regressing any metric (only
    the docstring text changes — same line count, same structure). Commit
    2, like the failing case above, touches only a markdown file. The whole
    branch diff includes the Python touch, but since nothing regressed the
    check must still pass.
    """
    repo = _init_repo_with_committed_baseline(tmp_path)
    _git(repo, "checkout", "-b", "feature")

    unchanged_metrics = _BASELINE_MODULE.replace(
        "ratchet touched-file window test", "ratchet touched-file window — no-op edit"
    )
    (repo / "pkg" / "mod.py").write_text(unchanged_metrics)
    _commit_all(repo, "commit 1: docstring wording only, no metric moves")

    (repo / "docs").mkdir()
    (repo / "docs" / "note.md").write_text("# Note\n")
    _commit_all(repo, "commit 2: docs only, no Python touched")

    result = _run_check_oo(repo, "pkg", "--check")

    assert result.returncode == 0, result.stdout + result.stderr


def test_fails_safe_to_none_when_no_target_ref_is_resolvable(tmp_path: Path) -> None:
    """No local ``main`` and no ``origin`` remote: the window must not fail open.

    ``GitDiffWindow`` must report ``None`` (compare every scored file
    against baseline) rather than an empty list — an empty list is exactly
    the false "nothing touched" signal this whole bug class is about.

    Probed via a ``python -c`` subprocess rather than importing ``oo_score``
    into this test process: ``tools/`` is a standalone-script directory, not
    a package on the type-checked source path, so importing it directly here
    would need an unresolvable-import suppression this test has no business
    asking for.
    """
    repo = tmp_path / "lonely"
    repo.mkdir()
    _git(repo, "init", "-b", "trunk")  # deliberately not "main"
    _git(repo, "config", "user.email", "rmh@punt-labs.test")
    _git(repo, "config", "user.name", "OO Ratchet Test")
    (repo / "a.py").write_text("x = 1\n")
    _commit_all(repo, "only commit")

    probe = (
        f"import sys; sys.path.insert(0, {str(_OO_SCORE.parent)!r}); "
        f"import oo_score; "
        f"print(oo_score.GitDiffWindow({str(repo)!r}).touched_files())"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )

    assert result.stdout.strip() == "None"
