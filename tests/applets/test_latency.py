"""ClickLatency — one line per click, saying where that click's time went.

A user who reports a slow click reports it by pasting a log line, so the line has
to carry the whole story: every stage that ran, in the order it ran, and the
total wait behind them. These tests hold that line to it — that the stages are
all there, that they are in order, that each carries its own duration rather than
the one beside it, and that one click produces exactly one line however it ended.
"""

from __future__ import annotations

import logging
import re
import time

import pytest

from punt_lux.applets.latency import ClickLatency


def _millis(line: str, stage: str) -> float:
    """The milliseconds ``line`` reports for ``stage`` — ``total`` included."""
    match = re.search(rf"{stage} (\d+) ms", line)
    if match is None:
        raise AssertionError(f"no {stage!r} in {line!r}")
    return float(match.group(1))


def test_every_stage_is_reported_on_one_line_in_the_order_it_was_spent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The whole point of the line: a click's stages, in the order the user felt.

    One line rather than one per stage, because the reader is a user who has been
    asked what happened — a story split across four lines is a story they have to
    reassemble before they can paste it.
    """
    latency = ClickLatency("beads")
    with latency.answering():
        pass
    with latency.stage("fetched"):
        pass
    with latency.stage("built"):
        pass
    with latency.stage("pushed"):
        pass

    with caplog.at_level(logging.INFO):
        latency.report()

    assert len(caplog.records) == 1
    line = caplog.records[0].getMessage()
    assert line.startswith("click beads:")
    assert (
        line.index("answered")
        < line.index("fetched")
        < line.index("built")
        < line.index("pushed")
        < line.index("total")
    )


def test_a_stage_carries_its_own_duration_and_not_its_neighbour_s(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A line that smeared the wait across the stages would name the wrong one."""
    latency = ClickLatency("beads")
    with latency.stage("fetched"):
        time.sleep(0.05)
    with latency.stage("built"):
        pass

    with caplog.at_level(logging.INFO):
        latency.report()

    line = caplog.records[0].getMessage()
    assert _millis(line, "fetched") >= 45  # the sleep landed where it happened
    assert _millis(line, "built") < _millis(line, "fetched")
    assert _millis(line, "total") >= _millis(line, "fetched")


def test_a_stage_that_failed_is_still_timed_and_still_raises(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The stage worth reading is often the one that ran for ages and then failed.

    Timing it must not swallow it: the servicing failure boundary above is what
    decides what a failed click renders, and it cannot decide if it never hears.
    """
    latency = ClickLatency("beads")
    with pytest.raises(RuntimeError), latency.stage("fetched"):
        time.sleep(0.05)
        raise RuntimeError("bd blew up")

    with caplog.at_level(logging.INFO):
        latency.report()

    line = caplog.records[0].getMessage()
    assert _millis(line, "fetched") >= 45
    assert "built" not in line  # and nothing after it claims to have run


def test_a_click_slower_than_its_budget_says_so(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A latency inside the budget is routine; one outside it is worth a warning."""
    latency = ClickLatency("beads")
    with latency.answering():
        time.sleep(0.12)  # past the 100 ms budget

    with caplog.at_level(logging.INFO):
        latency.report()

    assert len(caplog.records) == 1  # still one line, at a level that carries
    assert caplog.records[0].levelno == logging.WARNING
    assert "over the 100 ms budget" in caplog.text
    assert _millis(caplog.records[0].getMessage(), "answered") >= 115


def test_a_click_that_never_reached_a_stage_reports_no_breach(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A click that died before it was answered spent no time answering.

    Reporting it as over budget would blame the one stage that never ran, and the
    line is meant to say how far the click got — here, nowhere.
    """
    latency = ClickLatency("beads")
    time.sleep(0.12)  # longer than the budget, but not spent answering anything

    with caplog.at_level(logging.INFO):
        latency.report()

    assert caplog.records[0].levelno == logging.INFO
    assert _millis(caplog.records[0].getMessage(), "total") >= 115
