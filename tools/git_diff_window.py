"""The OO ratchet's touched-file window: the branch's whole diff, not one commit.

``GitDiffWindow.select()`` answers one question for ``tools/oo_score.py``: of
the files the scorer is looking at, which ones did this branch actually touch?
It windows against ``git merge-base <target> HEAD`` -- the target being
``origin/main`` (the remote-tracking merge target), falling back to local
``main`` -- so the window matches what a squash-merge actually lands on the
target branch: every commit on this branch,
not the last one. A ``HEAD~1..HEAD`` window hides a regression an earlier
commit left whenever the branch's final commit doesn't touch the regressed
file (a closing docs commit, say) -- that gap let regressions reach ``main``
invisibly, which is the failure this window closes.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Self


@dataclass(frozen=True, slots=True)
class _ResolvedWindow:
    """A git diff window that resolved to a real target, base, and file list."""

    target: str
    base_sha: str
    files: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _FailedWindow:
    """A git diff window that could not resolve -- diagnostic fields only.

    ``target`` is ``None`` when no candidate target ref could be resolved
    -- either none exists (no ``origin/main``, no local ``main``) or a git
    call raised before one was found. Either way there is nothing to name.
    ``base_sha`` is ``None`` whenever a base commit was never found: either
    ``target`` itself is ``None``, or ``target`` resolved but shares no
    common ancestor with ``HEAD`` (an orphan branch). Both are genuinely
    absent, not a value the type system gave up modeling (PY-TS-14) --
    there is no fallback value that would mean anything here.
    """

    target: str | None
    base_sha: str | None


_Window = _ResolvedWindow | _FailedWindow


class GitDiffWindow:
    """The touched-file set for the ratchet: the branch's whole diff.

    ``select()`` is the sole public entry point. It fails SAFE, never open:
    to the FULL scored set, never the empty one, whenever the window
    itself can't be resolved (no target ref, detached HEAD, no common
    ancestor, git unavailable). A resolved window's intersection with the
    scored files is trusted as-is, empty or not -- see ``select()`` for why.
    Every call emits one auditable diagnostic to stderr.
    """

    _root: Path

    _TIMEOUT: ClassVar[float] = 5
    _CANDIDATE_TARGETS: ClassVar[tuple[str, ...]] = ("origin/main", "main")

    def __new__(cls, root: Path) -> Self:
        self = super().__new__(cls)
        self._root = root
        return self

    def select(self, scored: set[str]) -> set[str]:
        """Return the subset of ``scored`` touched since diverging from the target.

        Always a subset of ``scored`` -- never ``None``, never a spurious
        empty set. Fails safe to the FULL ``scored`` set whenever the
        window itself can't be resolved (no target ref, no common
        ancestor, git unavailable) -- never to the empty set, which is the
        false "nothing touched" signal this class exists to stop
        producing. Emits one auditable diagnostic line to stderr either
        way, naming the resolved target, base SHA, and touched-vs-scored
        counts, and saying explicitly when the fallback fired.

        A *resolved* window's intersection with ``scored`` is trusted as
        the real answer, empty or not, once both sides are normalized to
        the same absolute-path form (below) -- that normalization is what
        makes an absolute-``SRC`` or subdirectory invocation match
        git's repo-root-relative diff correctly, closing the false
        trivial-pass class this method exists to fix. An empty
        intersection under a *scoped* ``--check`` (e.g. ``src/punt_lux/``)
        is not a mismatch to distrust -- it is the ordinary, frequent, and
        correct case where a branch's real diff lies entirely outside the
        scored subtree (a tools-, tests-, or docs-only change, for
        example). Falling back to the FULL tree on an empty scoped
        intersection would be wrong: it reclassifies every out-of-scope
        change as a full-tree regression. An empty *scoped* intersection
        is trusted; only an unresolved window falls back.
        """
        try:
            touched, window = self._select(scored)
        except (OSError, subprocess.SubprocessError):
            touched, window = scored, _FailedWindow(target=None, base_sha=None)
        self._diagnose(window, scored, touched)
        return touched

    def _select(self, scored: set[str]) -> tuple[set[str], _Window]:
        window = self._resolve_window()
        if isinstance(window, _FailedWindow):
            return scored, window

        repo_root = Path(self._repo_root())
        by_norm = {self._normalize(f, Path.cwd()): f for f in scored}
        hit = {self._normalize(f, repo_root) for f in window.files} & by_norm.keys()
        return {by_norm[n] for n in hit}, window

    @staticmethod
    def _normalize(raw: str, base: Path) -> str:
        """Return ``raw`` as an absolute path, anchored at ``base`` if relative."""
        path = Path(raw)
        return str(path.resolve() if path.is_absolute() else (base / path).resolve())

    def _resolve_window(self) -> _Window:
        target = self._resolve_target()
        if target is None:
            return _FailedWindow(target=None, base_sha=None)
        head_sha = self._rev_parse("HEAD")
        target_sha = self._rev_parse(target)
        if head_sha == target_sha:
            # Squash-merge workflow, `make check` before every commit to
            # main (see WORKFLOW.md): on the target ref itself,
            # HEAD~1..HEAD IS the whole landed change -- no multi-commit
            # branch can hide there. Revisit if non-squash merges to main
            # are ever adopted.
            return _ResolvedWindow(target, head_sha, self._diff("HEAD~1", "HEAD"))
        base = self._merge_base(target)
        if base is None:
            return _FailedWindow(target=target, base_sha=None)
        return _ResolvedWindow(target, base, self._diff(base, "HEAD"))

    def _resolve_target(self) -> str | None:
        for ref in self._CANDIDATE_TARGETS:
            result = self._run(["git", "rev-parse", "--verify", "--quiet", ref])
            if result.returncode == 0:
                return ref
        return None

    def _rev_parse(self, ref: str) -> str:
        """Return the SHA for ``ref``.

        Trusts ``ref`` resolves: ``HEAD`` always does in a repo with any
        commit, and ``target`` was already ``--verify``'d by
        ``_resolve_target``. A failure here means the repo changed under us
        mid-run -- a genuinely exceptional condition that belongs at
        ``select()``'s boundary catch, not a third Optional layer over an
        already-checked ref (PL-PP-3).
        """
        result = self._run(["git", "rev-parse", ref], check=True)
        return result.stdout.strip()

    def _repo_root(self) -> str:
        """Return the repo's top-level directory, absolute.

        Same trust rationale as ``_rev_parse``: every prior git call in
        this window already succeeded, so this one failing is a boundary
        condition, not a normal outcome to model as an Optional.
        """
        result = self._run(["git", "rev-parse", "--show-toplevel"], check=True)
        return result.stdout.strip()

    def _merge_base(self, target: str) -> str | None:
        result = self._run(["git", "merge-base", target, "HEAD"])
        if result.returncode != 0:
            return None
        base = result.stdout.strip()
        return base or None

    def _diff(self, base: str, head: str) -> tuple[str, ...]:
        """Return the files changed between ``base`` and ``head``.

        ``check=True``: a diff failure here is a boundary condition (the
        repo changed under us mid-run, same as ``_rev_parse``), not a
        normal outcome -- it propagates as ``CalledProcessError``
        (a ``subprocess.SubprocessError``) for ``select()``'s existing
        catch to fail safe on, rather than a second None-sentinel layered
        under the window's own resolved/failed split.

        ``core.quotepath=false`` keeps non-ASCII filenames un-escaped so
        they still match the scorer's own paths. A filename containing a
        literal quote, tab, or newline is still C-quoted regardless --
        vanishingly rare for a ``.py`` module, acknowledged and not
        handled.
        """
        result = self._run(
            [
                "git",
                "-c",
                "core.quotepath=false",
                "diff",
                "--name-only",
                f"{base}..{head}",
            ],
            check=True,
        )
        return tuple(line for line in result.stdout.strip().splitlines() if line)

    def _run(
        self,
        argv: list[str],
        *,
        check: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=self._TIMEOUT,
            cwd=self._root,
            check=check,
        )

    @staticmethod
    def _diagnose(window: _Window, scored: set[str], touched: set[str]) -> None:
        fell_back = isinstance(window, _FailedWindow)
        note = " -- SCORE-EVERYTHING FALLBACK" if fell_back else ""
        sys.stderr.write(
            f"oo_score: git window target={window.target} base={window.base_sha} "
            f"touched={len(touched)}/{len(scored)} scored{note}\n",
        )
