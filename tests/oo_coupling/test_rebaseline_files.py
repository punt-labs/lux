"""Coverage for ``CouplingRatchet.rebaseline_files`` -- DES-096's scoped bless.

DES-096 authorizes a bounded, scoped, tool-computed bless: ``--rebaseline-files``
records the CURRENT (recomputed) baseline for exactly the named files, and
refuses -- writing nothing to either the baseline or the audit log -- when a
named file's recomputed value strictly EXCEEDS its absolute PL-CU-1 threshold
(a value exactly AT the cap is within-threshold and is recorded), or when a
named path was never scored at all. Refusal is per-file, not all-or-nothing:
a named file that clears its cap is still blessed even if another named file
in the same call is refused. Every bless requires a caller-supplied
``reason``, recorded in the audit entry -- the tool cannot judge "genuinely
necessary first edge," so the human-supplied justification is the
accountability.

These tests exercise: (1) a within-threshold regression IS recorded, (2) an
over-threshold value is REFUSED with nothing written for it, (3) files not
named in the bless are never touched, (4) a circular-import regression (an
``==`` threshold, not a ``<=`` one) is refused the same way, (5) a value
exactly AT the cap is accepted while one strictly over it is refused, in the
same call, without one blocking the other, and (6) the CLI-level requirement
that ``--rebaseline-files`` without ``--reason`` fails before anything is
written to either the baseline or the audit log.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Self

import pytest

from tools import oo_coupling
from tools.oo_coupling import CouplingRatchet, CouplingScorer

_HEADER = "from __future__ import annotations\n\n\n"
_REASON = "DES-096 test bless: exercising the guardrail"


def _stub_module(name: str) -> str:
    """Return source for a trivial internal module with no internal imports."""
    return f'{_HEADER}"""Stub dependency module {name}."""\n'


def _importer(deps: list[str]) -> str:
    """Return source for a module importing each of ``deps`` by top-level name."""
    imports = "\n".join(f"import {dep}" for dep in deps)
    return f"{_HEADER}{imports}\n"


class RebaselineFilesFixture:
    """A throwaway flat package for exercising ``rebaseline_files`` directly.

    Flat (no sub-packages) so every dependency module is a top-level stem in
    ``_discover_package_modules`` -- the simplest shape that produces a
    controllable ``efferent_coupling`` count on the importing module.
    """

    _root: Path

    def __new__(cls, tmp: Path) -> Self:
        self = super().__new__(cls)
        self._root = tmp
        return self

    @property
    def root(self) -> Path:
        return self._root

    def write(self, name: str, content: str) -> None:
        (self._root / name).write_text(content)

    def write_baseline(self, entries: dict[str, dict[str, float]]) -> None:
        (self._root / CouplingRatchet.BASELINE_FILE).write_text(
            json.dumps(entries, indent=2) + "\n",
        )

    def path(self, name: str) -> str:
        """Return the scored-key form of ``name`` -- an absolute path string."""
        return str(self._root / name)

    def scorer(self) -> CouplingScorer:
        return CouplingScorer(self._root)

    def ratchet(self) -> CouplingRatchet:
        return CouplingRatchet(self._root)

    def baseline(self) -> dict[str, dict[str, float]]:
        text = (self._root / CouplingRatchet.BASELINE_FILE).read_text()
        result: dict[str, dict[str, float]] = json.loads(text)
        return result

    def audit_lines(self) -> list[str]:
        audit_path = self._root / CouplingRatchet.AUDIT_FILE
        if not audit_path.exists():
            return []
        return [line for line in audit_path.read_text().splitlines() if line.strip()]


def test_within_threshold_regression_is_recorded(tmp_path: Path) -> None:
    """A regression that stays under the absolute cap is blessed and logged."""
    fx = RebaselineFilesFixture(tmp_path)
    for i in range(1, 6):
        fx.write(f"dep{i}.py", _stub_module(f"dep{i}"))
    fx.write("target.py", _importer(["dep1", "dep2", "dep3"]))
    fx.write_baseline(CouplingRatchet._results_by_file(fx.scorer().results))

    # Regress target.py to a higher, still-within-threshold (<= 7) coupling.
    fx.write("target.py", _importer(["dep1", "dep2", "dep3", "dep4", "dep5"]))
    target = fx.path("target.py")

    exit_code = fx.ratchet().rebaseline_files(fx.scorer(), [target], _REASON)

    assert exit_code == 0
    recorded = fx.baseline()[target]
    assert recorded["efferent_coupling"] == 5

    audit_lines = fx.audit_lines()
    assert len(audit_lines) == 1
    entry = json.loads(audit_lines[0])
    assert entry["verdict"] == "rebaseline-files"
    assert entry["reason"] == _REASON
    assert entry["files_scored"] == 1
    assert entry["files_regressed"] == 1
    assert entry["deltas"][target]["efferent_coupling"] == [3, 5]


def test_over_threshold_value_is_refused_and_nothing_written(tmp_path: Path) -> None:
    """A value that strictly exceeds the cap is refused; nothing writes."""
    fx = RebaselineFilesFixture(tmp_path)
    for i in range(1, 10):
        fx.write(f"dep{i}.py", _stub_module(f"dep{i}"))
    fx.write("target.py", _importer([f"dep{i}" for i in range(1, 4)]))
    baseline_before = CouplingRatchet._results_by_file(fx.scorer().results)
    fx.write_baseline(baseline_before)

    # 9 imports pushes efferent_coupling past the <= 7 absolute threshold.
    fx.write("target.py", _importer([f"dep{i}" for i in range(1, 10)]))
    target = fx.path("target.py")

    exit_code = fx.ratchet().rebaseline_files(fx.scorer(), [target], _REASON)

    assert exit_code == 1
    assert fx.baseline() == baseline_before
    assert fx.audit_lines() == []


def test_unnamed_file_baseline_never_touched(tmp_path: Path) -> None:
    """Only the named file's baseline entry moves; every other entry is frozen."""
    fx = RebaselineFilesFixture(tmp_path)
    fx.write("dep1.py", _stub_module("dep1"))
    fx.write("dep2.py", _stub_module("dep2"))
    fx.write("target.py", _importer(["dep1"]))
    fx.write("other.py", _importer(["dep1"]))
    baseline_before = CouplingRatchet._results_by_file(fx.scorer().results)
    fx.write_baseline(baseline_before)

    # Regress BOTH files -- only target.py is named in the bless.
    fx.write("target.py", _importer(["dep1", "dep2"]))
    fx.write("other.py", _importer(["dep1", "dep2"]))
    target = fx.path("target.py")
    other = fx.path("other.py")

    exit_code = fx.ratchet().rebaseline_files(fx.scorer(), [target], _REASON)

    assert exit_code == 0
    recorded = fx.baseline()
    assert recorded[target]["efferent_coupling"] == 2
    assert recorded[other] == baseline_before[other]


def test_circular_import_regression_is_refused(tmp_path: Path) -> None:
    """circular_imports is an ``== 0`` threshold; a new cycle (1) is refused."""
    fx = RebaselineFilesFixture(tmp_path)
    fx.write("a.py", _importer(["b"]))
    fx.write("b.py", _stub_module("b"))
    baseline_before = CouplingRatchet._results_by_file(fx.scorer().results)
    fx.write_baseline(baseline_before)

    # Introduce a cycle: b now imports a back.
    fx.write("b.py", _importer(["a"]))
    a_path = fx.path("a.py")

    exit_code = fx.ratchet().rebaseline_files(fx.scorer(), [a_path], _REASON)

    assert exit_code == 1
    assert fx.baseline() == baseline_before
    assert fx.audit_lines() == []


def test_missing_path_is_refused(tmp_path: Path) -> None:
    """A path absent from the scored tree is refused -- nothing written."""
    fx = RebaselineFilesFixture(tmp_path)
    fx.write("target.py", _stub_module("target"))
    baseline_before = CouplingRatchet._results_by_file(fx.scorer().results)
    fx.write_baseline(baseline_before)

    missing = fx.path("nonexistent.py")

    exit_code = fx.ratchet().rebaseline_files(fx.scorer(), [missing], _REASON)

    assert exit_code == 1
    assert fx.baseline() == baseline_before
    assert fx.audit_lines() == []


def test_at_cap_accepted_over_cap_refused_same_call(tmp_path: Path) -> None:
    """The cap is inclusive; refusal is per-file, not all-or-nothing.

    ``at_cap.py`` recomputes to exactly 7 imports (the ``<= 7`` threshold) and
    must be blessed. ``over_cap.py`` recomputes to 8 and must be refused. Both
    are named in the SAME call: the refused file does not block the accepted
    one, and the accepted file's write does not silence the refusal.
    """
    fx = RebaselineFilesFixture(tmp_path)
    for i in range(1, 9):
        fx.write(f"dep{i}.py", _stub_module(f"dep{i}"))
    fx.write("at_cap.py", _importer(["dep1"]))
    fx.write("over_cap.py", _importer(["dep1"]))
    baseline_before = CouplingRatchet._results_by_file(fx.scorer().results)
    fx.write_baseline(baseline_before)

    fx.write("at_cap.py", _importer([f"dep{i}" for i in range(1, 8)]))  # 7 -> at cap
    fx.write("over_cap.py", _importer([f"dep{i}" for i in range(1, 9)]))  # 8 -> over

    at_cap = fx.path("at_cap.py")
    over_cap = fx.path("over_cap.py")

    exit_code = fx.ratchet().rebaseline_files(fx.scorer(), [at_cap, over_cap], _REASON)

    assert exit_code == 1  # a refusal occurred, even though one file blessed fine
    recorded = fx.baseline()
    assert recorded[at_cap]["efferent_coupling"] == 7  # blessed, not blocked
    assert recorded[over_cap] == baseline_before[over_cap]  # refused, untouched

    audit_lines = fx.audit_lines()
    assert len(audit_lines) == 1
    entry = json.loads(audit_lines[0])
    assert entry["files_scored"] == 1  # only the accepted file was recorded
    assert at_cap in entry["deltas"]
    assert over_cap not in entry["deltas"]


def test_cli_rebaseline_files_without_reason_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--rebaseline-files`` without ``--reason`` fails before anything writes."""
    fx = RebaselineFilesFixture(tmp_path)
    fx.write("target.py", _stub_module("target"))
    baseline_before = CouplingRatchet._results_by_file(fx.scorer().results)
    fx.write_baseline(baseline_before)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["oo_coupling.py", str(tmp_path), "--rebaseline-files", fx.path("target.py")],
    )

    with pytest.raises(SystemExit) as exc_info:
        oo_coupling.main()

    assert exc_info.value.code == 1
    assert fx.baseline() == baseline_before
    assert fx.audit_lines() == []
