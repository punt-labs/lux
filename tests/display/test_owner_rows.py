"""OwnerRows — replicated facts, an explicit unknown row, one warning per open."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from punt_lux.display.menus.open_popup import OpenFrame
from punt_lux.display.menus.owner_rows import OwnerRows
from punt_lux.domain.identity import HubId

if TYPE_CHECKING:
    import pytest

_HUB = HubId.stub()
_FRAME = OpenFrame("f1", _HUB)
_ROWS = (("Client", "lux"),)
_UNKNOWN = (("Owner", "unknown"),)


def _rows(resolved: tuple[tuple[str, str], ...] | None) -> OwnerRows:
    return OwnerRows(lambda _frame_id, _hub: resolved)


def test_replicated_facts_are_returned_for_open() -> None:
    assert _rows(_ROWS).for_open(_FRAME) == _ROWS


def test_missing_facts_open_with_the_unknown_row() -> None:
    assert _rows(None).for_open(_FRAME) == _UNKNOWN


def test_resolved_but_empty_facts_are_not_unknown() -> None:
    assert _rows(()).for_open(_FRAME) == ()


def test_missing_facts_warn_on_open_naming_hub_and_frame(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="punt_lux.display.menus"):
        _rows(None).for_open(_FRAME)
    assert f"hub={_HUB} frame=f1" in caplog.text


def test_replicated_facts_do_not_warn_on_open(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="punt_lux.display.menus"):
        _rows(_ROWS).for_open(_FRAME)
    assert caplog.records == []


def test_refresh_returns_the_unknown_row_without_logging(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG, logger="punt_lux.display.menus"):
        rows = _rows(None).for_refresh(_FRAME)
    assert rows == _UNKNOWN
    assert caplog.records == []
