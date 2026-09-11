"""The ``--rebaseline-files`` bless: bounded, scoped, tool-computed (DES-097).

The OO-ratchet analog of the coupling ratchet's ``--rebaseline-files``
(DES-096): a genuinely-necessary within-cap regression may be recorded even
though ``--update``/``--reconcile`` would refuse it outright. Four properties
keep this from becoming a suppression loophole: bounded (a metric refuses
only when it BOTH exceeds its absolute cap AND regressed against the file's
committed baseline, see :meth:`PlanApplier.over_cap_and_regressed`),
tool-computed (every recorded number comes from the caller's scored
``current`` snapshot, never from an argument), scoped (only the named
``paths`` are touched -- every other file's baseline entry is untouched), and
audit-logged (every bless appends a ``"rebaseline-files"`` entry to
``.oo-audit.jsonl`` naming the caller-supplied ``reason`` -- the tool cannot
judge "genuinely necessary," so the human-supplied reason plus this record
are the accountability).
"""

from __future__ import annotations

from pathlib import Path
from typing import Self

from .apply import PlanApplier
from .audit import AuditLog
from .baseline import Baseline
from .gitio import GitRepo
from .outcome import Outcome
from .thresholds import Thresholds


class FileBless:
    """Gate, write, audit, and report one ``--rebaseline-files`` invocation."""

    _baseline: Baseline
    _audit: AuditLog
    _git: GitRepo

    def __new__(cls, baseline: Baseline, audit: AuditLog, git: GitRepo) -> Self:
        self = super().__new__(cls)
        self._baseline = baseline
        self._audit = audit
        self._git = git
        return self

    def apply(
        self,
        current: dict[str, dict[str, float]],
        paths: list[str],
        *,
        reason: str,
        source: str | None,
    ) -> Outcome:
        """Bless the named ``paths`` against ``current``, refusing gated metrics.

        The refusal is per-metric, per-file, not all-or-nothing across the
        whole call: a named file with any metric that fails the gate is
        refused -- excluded from the baseline write, reported, and never
        recorded -- while every other named file that clears its gate is
        still blessed. The same holds for a named path absent from ``current``.
        Returns exit code 0 only when every named file was blessed; 1
        whenever at least one was refused, even if the rest were written.
        """
        accepted, accepted_current, refused = self._partition(current, paths)
        if accepted:
            self._write(accepted, accepted_current, reason=reason, source=source)
        return self._report(accepted, refused, reason)

    def _resolved_index(self, current: dict[str, dict[str, float]]) -> dict[Path, str]:
        """Map each scored file's resolved absolute path back to its key.

        ``Scorer`` already normalizes every key to repo-relative POSIX, so
        there is exactly one canonical key per file. A caller may still
        spell a requested path differently (absolute, a "./" prefix, a
        redundant segment); resolving both sides to the same absolute form
        lets a genuinely-scored file be matched regardless of spelling.
        """
        root = self._baseline.path.parent
        return {(root / key).resolve(): key for key in current}

    def _partition(
        self, current: dict[str, dict[str, float]], paths: list[str]
    ) -> tuple[list[str], dict[str, dict[str, float]], list[tuple[str, str]]]:
        """Split ``paths`` into accepted (cleared the gate) and refused."""
        resolved_index = self._resolved_index(current)
        accepted: list[str] = []
        accepted_current: dict[str, dict[str, float]] = {}
        refused: list[tuple[str, str]] = []
        for requested in paths:
            path = self._resolve(requested, current, resolved_index)
            if path is None:
                refused.append((requested, "not found in scored tree"))
                continue
            entry = current[path]
            gated = PlanApplier.over_cap_and_regressed(entry, self._baseline.get(path))
            if gated:
                refused.append((requested, self._gate_detail(entry, gated)))
                continue
            accepted.append(path)
            accepted_current[path] = entry
        return accepted, accepted_current, refused

    @staticmethod
    def _resolve(
        requested: str,
        current: dict[str, dict[str, float]],
        resolved_index: dict[Path, str],
    ) -> str | None:
        if requested in current:
            return requested
        return resolved_index.get(Path(requested).resolve())

    @staticmethod
    def _gate_detail(entry: dict[str, float], gated: list[str]) -> str:
        return "; ".join(
            f"{m}={entry[m]:g} fails {Thresholds.describe(m)} (over cap and regressed)"
            for m in gated
        )

    def _write(
        self,
        accepted: list[str],
        accepted_current: dict[str, dict[str, float]],
        *,
        reason: str,
        source: str | None,
    ) -> None:
        new_baseline = dict(self._baseline.entries)
        deltas: dict[str, dict[str, list[float]]] = {}
        regressed_files: set[str] = set()
        improved_files: set[str] = set()
        for path in accepted:
            entry = accepted_current[path]
            base_entry = self._baseline.get(path)
            file_deltas = PlanApplier.deltas(entry, base_entry)
            if file_deltas:
                deltas[path] = file_deltas
            if base_entry is not None:
                self._classify(
                    path,
                    entry,
                    base_entry,
                    file_deltas,
                    regressed_files,
                    improved_files,
                )
            new_baseline[path] = entry
        # A file with any regressed metric is counted as regressed, not
        # improved, even if another of its metrics also improved -- "improved"
        # is reserved for a bless whose deltas are a pure improvement, never a
        # regression riding alongside one.
        files_improved = len(improved_files - regressed_files)
        self._audit.append(
            files_scored=len(accepted),
            files_improved=files_improved,
            files_regressed=len(regressed_files),
            verdict="rebaseline-files",
            deltas=deltas,
            source=source,
            commit=self._git.short_head(),
            reason=reason,
        )
        self._baseline.save(new_baseline)

    @staticmethod
    def _classify(
        path: str,
        entry: dict[str, float],
        base_entry: dict[str, float],
        file_deltas: dict[str, list[float]],
        regressed_files: set[str],
        improved_files: set[str],
    ) -> None:
        for metric in file_deltas:
            cur, base = entry[metric], base_entry[metric]
            if not Thresholds.better_or_equal(metric, cur, base):
                regressed_files.add(path)
            elif Thresholds.strictly_better(metric, cur, base):
                improved_files.add(path)

    @staticmethod
    def _report(
        accepted: list[str], refused: list[tuple[str, str]], reason: str
    ) -> Outcome:
        lines = [f"\nBaseline blessed for {len(accepted)} file(s) (reason: {reason}):"]
        lines.append("  files:" if accepted else "  (none)")
        lines.extend(f"    {path}" for path in accepted)
        if refused:
            lines.append(f"  REFUSED ({len(refused)} file(s), nothing written):")
            lines.extend(f"    {path}: {why}" for path, why in refused)
        return Outcome(1 if refused else 0, tuple(lines))
