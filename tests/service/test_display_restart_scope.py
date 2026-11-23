"""Per-attempt process queries and diagnostics share one hard deadline."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from punt_lux.service import DISPLAY_SPEC
from punt_lux.service._display_restart_attempt import ReadinessError, RestartAttempt
from punt_lux.service._display_restart_scope import DisplayRestartScope


@pytest.mark.parametrize("remaining,queries", [(1, 0), (2, 1)])
def test_query_starts_only_if_the_fixed_timeout_fits(
    remaining: int,
    queries: int,
) -> None:
    with (
        patch("punt_lux.service._readiness_http.time.monotonic") as clock,
        patch("punt_lux.service._backends.pgrep_pid", return_value=502) as lookup,
    ):
        clock.return_value = 0
        scope = DisplayRestartScope(
            RestartAttempt(DISPLAY_SPEC, 501, 0, 30), MagicMock()
        )
        assert scope.before == 501
        clock.return_value = 30 - remaining
        if queries:
            assert scope.pid((None, False)) == 502
        else:
            with pytest.raises(ReadinessError, match="within 30s"):
                scope.pid((None, False))
        assert lookup.call_count == queries


@pytest.mark.parametrize("elapsed", [28.5, 29.5, 30])
def test_known_candidate_skips_lookup_but_never_the_deadline(elapsed: float) -> None:
    with (
        patch("punt_lux.service._readiness_http.time.monotonic") as clock,
        patch("punt_lux.service._backends.pgrep_pid") as lookup,
    ):
        clock.return_value = 0
        scope = DisplayRestartScope(
            RestartAttempt(DISPLAY_SPEC, 501, 0, 30), MagicMock()
        )
        clock.return_value = elapsed
        if elapsed < 30:
            assert scope.pid((502, True)) == 502
        else:
            with pytest.raises(ReadinessError, match="within 30s"):
                scope.pid((502, True))
        lookup.assert_not_called()


@pytest.mark.parametrize("status", [503, 504, 500])
def test_http_status_errors_remain_pending_until_the_deadline(status: int) -> None:
    with (
        patch("punt_lux.service._readiness_http.time.monotonic") as clock,
        patch(
            "punt_lux.service._hub_display_probe.HubDisplayProbe.connected",
            side_effect=ConnectionError(f"Hub Display probe returned HTTP {status}"),
        ),
    ):
        clock.return_value = 0
        scope = DisplayRestartScope(
            RestartAttempt(DISPLAY_SPEC, 501, 0, 30), MagicMock()
        )
        assert scope.connected(502, stabilizing=False) is None
        clock.return_value = 30
        with pytest.raises(ReadinessError, match=f"HTTP {status}"):
            scope.remaining(stabilizing=False)
