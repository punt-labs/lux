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
same call, without one blocking the other, (6) the CLI-level requirement
that ``--rebaseline-files`` without ``--reason`` fails before anything is
written to either the baseline or the audit log -- and never even
constructs the ``CouplingScorer``, (7) a path named in a non-canonical but
equivalent form is still resolved and blessed, (8) a blessed file whose
recomputed values exactly match the existing baseline still gets a full
audit entry rather than silently vanishing from ``deltas``, (9) a baseline
write failure never leaves a bless recorded-in-baseline-but-missing-from-
audit, (10) legacy ``--update``/``--rebaseline`` audit entries omit the
``reason`` key entirely rather than serializing ``"reason": null``, and (11)
a refused ``__main__.py`` file cites its own relaxed cap, not the default one.
"""

from __future__ import annotations

import contextlib
import io
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


def test_cli_missing_reason_never_constructs_scorer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing/blank ``--reason`` is rejected before ``CouplingScorer`` runs.

    Regression guard for the ordering bug: ``main()`` used to build
    ``CouplingScorer(target)`` -- walking and scoring the whole tree -- BEFORE
    checking that ``--reason`` was supplied, so a missing reason wasted a
    full scoring pass (and could fail on a bad ``--target`` with a less
    specific error) before ever reaching the intended message. Replacing
    ``CouplingScorer`` with a stub that raises if constructed proves the
    fixed ordering: the reason check must fail first, so the stub is never
    invoked and the raised ``AssertionError`` never surfaces.
    """
    fx = RebaselineFilesFixture(tmp_path)
    fx.write("target.py", _stub_module("target"))
    baseline_before = CouplingRatchet._results_by_file(fx.scorer().results)
    fx.write_baseline(baseline_before)

    def _must_not_construct(*_args: object, **_kwargs: object) -> CouplingScorer:
        raise AssertionError("CouplingScorer must not be constructed before --reason")

    monkeypatch.setattr(oo_coupling, "CouplingScorer", _must_not_construct)
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


def test_non_canonical_path_form_is_still_blessed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A path named in a different but equivalent form is still resolved.

    The scored key is the absolute path ``CouplingScorer`` produced. Naming
    the same file relative to the current working directory -- a spelling
    that never matches the scored key byte-for-byte -- must still resolve
    to it and be blessed, not refused as "not found in scored tree".
    """
    fx = RebaselineFilesFixture(tmp_path)
    for i in range(1, 6):
        fx.write(f"dep{i}.py", _stub_module(f"dep{i}"))
    fx.write("target.py", _importer(["dep1", "dep2", "dep3"]))
    fx.write_baseline(CouplingRatchet._results_by_file(fx.scorer().results))

    fx.write("target.py", _importer(["dep1", "dep2", "dep3", "dep4", "dep5"]))
    canonical = fx.path("target.py")

    monkeypatch.chdir(tmp_path)
    non_canonical = "./target.py"  # never equals `canonical` as a string

    exit_code = fx.ratchet().rebaseline_files(fx.scorer(), [non_canonical], _REASON)

    assert exit_code == 0
    recorded = fx.baseline()[canonical]  # written under the scorer's own key
    assert recorded["efferent_coupling"] == 5


def test_unchanged_file_still_gets_an_audit_entry(tmp_path: Path) -> None:
    """A blessed file whose values match the existing baseline is still audited.

    Every accepted file must appear in the audit entry's ``deltas``, even one
    whose recomputed values happen to exactly match what is already
    recorded -- it must not silently vanish just because nothing moved.
    """
    fx = RebaselineFilesFixture(tmp_path)
    fx.write("dep1.py", _stub_module("dep1"))
    fx.write("unchanged.py", _importer(["dep1"]))
    baseline_before = CouplingRatchet._results_by_file(fx.scorer().results)
    fx.write_baseline(baseline_before)

    unchanged = fx.path("unchanged.py")
    # No source change -- recomputing unchanged.py yields the same values.
    exit_code = fx.ratchet().rebaseline_files(fx.scorer(), [unchanged], _REASON)

    assert exit_code == 0
    audit_lines = fx.audit_lines()
    assert len(audit_lines) == 1
    entry = json.loads(audit_lines[0])
    assert entry["files_scored"] == 1
    assert unchanged in entry["deltas"]  # present even though nothing moved
    assert entry["deltas"][unchanged]["efferent_coupling"] == [1, 1]


def test_baseline_write_failure_leaves_audit_trail_not_silently_lost(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A baseline write failure never leaves a bless unlogged.

    ``rebaseline_files`` appends the audit entry BEFORE writing the
    baseline, specifically so a bless is never recorded-in-baseline-but-
    missing-from-audit. Simulating a baseline write failure proves the
    ordering: the audit entry is on disk, and the exception propagates
    (fails loud) rather than being swallowed.
    """
    fx = RebaselineFilesFixture(tmp_path)
    for i in range(1, 6):
        fx.write(f"dep{i}.py", _stub_module(f"dep{i}"))
    fx.write("target.py", _importer(["dep1", "dep2", "dep3"]))
    baseline_before = CouplingRatchet._results_by_file(fx.scorer().results)
    fx.write_baseline(baseline_before)

    fx.write("target.py", _importer(["dep1", "dep2", "dep3", "dep4", "dep5"]))
    target = fx.path("target.py")

    def _raise(*_args: object, **_kwargs: object) -> None:
        raise OSError("simulated disk failure")

    monkeypatch.setattr(CouplingRatchet, "_save_baseline", _raise)

    ratchet = fx.ratchet()
    with pytest.raises(OSError, match="simulated disk failure"):
        ratchet.rebaseline_files(fx.scorer(), [target], _REASON)

    assert fx.baseline() == baseline_before  # the baseline write never landed
    audit_lines = fx.audit_lines()
    assert len(audit_lines) == 1  # but the audit entry was already recorded
    entry = json.loads(audit_lines[0])
    assert entry["verdict"] == "rebaseline-files"
    assert entry["deltas"][target]["efferent_coupling"] == [3, 5]


def test_update_and_rebaseline_audit_entries_omit_reason_key(tmp_path: Path) -> None:
    """Legacy ``--update``/``--rebaseline`` entries have no "reason" key at all.

    ``_append_audit`` grew an optional ``reason`` kwarg for
    ``rebaseline_files``; it must not leak a ``"reason": null`` field into
    the legacy verdicts' entries -- that would change their schema.
    """
    fx = RebaselineFilesFixture(tmp_path)
    fx.write("target.py", _stub_module("target"))

    fx.ratchet().update(fx.scorer())
    fx.ratchet().rebaseline(fx.scorer())

    audit_lines = fx.audit_lines()
    assert len(audit_lines) == 2
    for line in audit_lines:
        entry = json.loads(line)
        assert "reason" not in entry


def test_dunder_main_refusal_cites_relaxed_cap(tmp_path: Path) -> None:
    """A refused ``__main__.py`` file cites its own relaxed cap, not the default.

    ``__main__.py`` is judged against ``MAIN_THRESHOLDS``
    (``efferent_coupling <= 15``), so 9 imports is within-threshold there
    even though it would exceed the default ``<= 7``, and 16 imports is
    refused citing "<= 15" -- the cap it was actually judged against --
    never the unrelated default "<= 7".
    """
    fx = RebaselineFilesFixture(tmp_path)
    for i in range(1, 17):
        fx.write(f"dep{i}.py", _stub_module(f"dep{i}"))
    fx.write("__main__.py", _importer([f"dep{i}" for i in range(1, 3)]))
    fx.write_baseline(CouplingRatchet._results_by_file(fx.scorer().results))
    main_path = fx.path("__main__.py")

    # 9 imports: over the default <= 7 cap, but under __main__.py's relaxed
    # <= 15 -- must be ACCEPTED, proving the relaxed cap is the one applied.
    fx.write("__main__.py", _importer([f"dep{i}" for i in range(1, 10)]))
    exit_code = fx.ratchet().rebaseline_files(fx.scorer(), [main_path], _REASON)
    assert exit_code == 0

    # 16 imports: over even the relaxed <= 15 cap -- refused, and the
    # message must cite "<= 15", never the unrelated default "<= 7".
    fx.write("__main__.py", _importer([f"dep{i}" for i in range(1, 17)]))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exit_code = fx.ratchet().rebaseline_files(fx.scorer(), [main_path], _REASON)

    assert exit_code == 1
    output = buf.getvalue()
    assert "<= 15" in output
    assert "<= 7" not in output
