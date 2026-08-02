"""DoctorReport — what the lines add up to, and what counts as a failure.

The counting rule is the whole point: an advisory check colours the report
without turning a working installation into a non-zero exit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from punt_lux.doctor_report import FAIL, OK, OPTIONAL, DoctorReport

if TYPE_CHECKING:
    import pytest


def test_a_fresh_report_has_failed_nothing() -> None:
    assert DoctorReport().failed == 0


def test_only_a_required_failure_counts_against_the_exit() -> None:
    report = DoctorReport()
    report(FAIL, "a display that is not up", required=False)
    report(OPTIONAL, "fonts not found", required=False)
    assert report.failed == 0

    report(FAIL, "python too old")
    assert report.failed == 1


def test_the_rendered_report_carries_its_lines_and_its_tally() -> None:
    report = DoctorReport()
    report(OK, "python 3.14")
    report(FAIL, "no luxd")

    rendered = report.render().splitlines()

    assert rendered[0] == "=" * 40
    assert rendered[1] == f"{OK} python 3.14"
    assert rendered[2] == f"{FAIL} no luxd"
    assert rendered[3] == "=" * 40
    assert rendered[4] == "1 passed, 1 failed"


def test_the_report_is_returned_not_printed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The command owns the terminal; the report only knows what it says."""
    report = DoctorReport()
    report(OK, "python 3.14")
    rendered = report.render()
    assert "python 3.14" in rendered
    assert capsys.readouterr().out == ""
