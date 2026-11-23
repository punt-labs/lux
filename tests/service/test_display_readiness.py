"""A listening Display is not ready until the Hub observes the same stable PID."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from punt_lux.service import DISPLAY_SPEC
from punt_lux.service._display_readiness import DisplayReadiness
from punt_lux.service._display_restart_attempt import (
    ReadinessError,
    RestartAttempt,
)
from punt_lux.service._display_restart_scope import DisplayRestartScope
from punt_lux.service._hub_display_probe import HubDisplayProbe
from punt_lux.service.display_restart import DisplayRestart, DisplayRestartError
from tests.service._probe_double import ProbeDouble


@pytest.fixture
def paths() -> Iterator[MagicMock]:
    result = MagicMock()
    result.peer_pid.return_value = 502
    with patch(
        "punt_lux.service._readiness_probe.ReadinessProbe.local",
        new=ProbeDouble.local,
    ):
        yield result


def test_success_requires_three_seconds_of_matching_hub_facts(paths: MagicMock) -> None:
    with (
        patch("punt_lux.service._display_readiness.time.monotonic") as clock,
        patch(
            "punt_lux.service._hub_display_probe.HubDisplayProbe.connected",
            autospec=True,
        ) as hub,
    ):
        clock.return_value = 0
        ready = DisplayReadiness(
            RestartAttempt(DISPLAY_SPEC, 501, time.time(), 30), paths
        )
        hub.return_value = False
        assert not ready.observe(502)
        clock.return_value = 2
        hub.return_value = True
        assert not ready.observe(502)
        clock.return_value = 4.99
        assert not ready.observe(502)
        clock.return_value = 5
        assert ready.observe(502)
    assert hub.call_args.args[0]._pid == 502
    assert hub.call_args.args[0]._timeout == 0.5


def test_a_known_candidate_can_complete_stability_in_the_last_second(
    paths: MagicMock,
) -> None:
    with (
        patch("punt_lux.service._display_readiness.time.monotonic") as clock,
        patch("punt_lux.service._backends.pgrep_pid", return_value=502) as lookup,
        patch(
            "punt_lux.service._hub_display_probe.HubDisplayProbe.connected",
            return_value="dial",
        ),
    ):
        clock.return_value = 0
        ready = DisplayReadiness(
            RestartAttempt(DISPLAY_SPEC, 501, time.time(), 30), paths
        )
        clock.return_value = 26.5
        assert not ready.observe(ready.pid())
        clock.return_value = 28.5
        assert not ready.observe(ready.pid())
        clock.return_value = 29.5
        assert ready.observe(ready.pid())
        lookup.assert_called_once_with(DISPLAY_SPEC.process_name)


@pytest.mark.parametrize("replacement", [None, 503])
def test_crash_before_hub_connect_fails_without_accepting_respawn(
    paths: MagicMock, replacement: int | None, caplog: pytest.LogCaptureFixture
) -> None:
    with patch(
        "punt_lux.service._hub_display_probe.HubDisplayProbe.connected",
        return_value=False,
    ):
        ready = DisplayReadiness(
            RestartAttempt(DISPLAY_SPEC, 501, time.time(), 30), paths
        )
        assert not ready.observe(502)
        with pytest.raises(ReadinessError, match="exited before connecting to Hub"):
            ready.observe(replacement)
    assert DISPLAY_SPEC.launchd_label in caplog.text
    assert caplog.records[-1].levelno == logging.ERROR


@pytest.mark.parametrize("loss", ["pid", "socket"])
def test_crash_or_disconnect_during_stability_fails(
    paths: MagicMock, loss: str
) -> None:
    with (
        patch("punt_lux.service._display_readiness.time.monotonic") as clock,
        patch(
            "punt_lux.service._hub_display_probe.HubDisplayProbe.connected",
            autospec=True,
        ) as hub,
    ):
        clock.return_value = 0
        hub.return_value = True
        ready = DisplayReadiness(
            RestartAttempt(DISPLAY_SPEC, 501, time.time(), 30), paths
        )
        assert not ready.observe(502)
        clock.return_value = 1.5
        if loss == "socket":
            paths.is_running.return_value = False
        with pytest.raises(ReadinessError, match=r"after 1\.5s connected to Hub"):
            ready.observe(None if loss == "pid" else 502)


def test_same_pid_on_a_replacement_hub_dial_restarts_the_window(
    paths: MagicMock,
) -> None:
    with (
        patch("punt_lux.service._display_readiness.time.monotonic") as clock,
        patch(
            "punt_lux.service._hub_display_probe.HubDisplayProbe.connected",
            autospec=True,
        ) as hub,
    ):
        clock.return_value = 0
        ready = DisplayReadiness(
            RestartAttempt(DISPLAY_SPEC, 501, time.time(), 30), paths
        )
        hub.return_value = "first-dial"
        assert not ready.observe(502)
        clock.return_value = 2.9
        hub.return_value = "replacement-dial"
        assert not ready.observe(502)
        clock.return_value = 3
        assert not ready.observe(502)
        clock.return_value = 5.9
        assert ready.observe(502)


def test_a_pending_hub_probe_restarts_stability_without_claiming_a_disconnect(
    paths: MagicMock,
) -> None:
    with (
        patch("punt_lux.service._display_readiness.time.monotonic") as clock,
        patch(
            "punt_lux.service._hub_display_probe.HubDisplayProbe.connected",
            autospec=True,
        ) as hub,
    ):
        clock.return_value = 0
        ready = DisplayReadiness(
            RestartAttempt(DISPLAY_SPEC, 501, time.time(), 30), paths
        )
        hub.return_value = "dial"
        assert not ready.observe(502)
        clock.return_value = 2
        hub.return_value = None
        assert not ready.observe(502)
        clock.return_value = 3
        hub.return_value = "dial"
        assert not ready.observe(502)
        clock.return_value = 6
        assert ready.observe(502)


def test_hub_unreachable_is_logged_and_becomes_existing_cli_error(
    paths: MagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        patch("punt_lux.service._backends.pgrep_pid", side_effect=[501, 502]),
        patch.object(DisplayRestart, "_polls", return_value=iter([None])),
        patch(
            "punt_lux.service._hub_display_probe.HubDisplayProbe.connected",
            side_effect=ConnectionError("Hub is not running"),
        ),
        pytest.raises(DisplayRestartError, match="Hub is not running"),
    ):
        DisplayRestart(manager=MagicMock(), paths=paths).run()
    assert "Hub is not running" in caplog.text
    assert DISPLAY_SPEC.launchd_label in caplog.text


def test_refused_hub_can_come_up_and_must_start_a_fresh_window(
    paths: MagicMock,
) -> None:
    with (
        patch("punt_lux.service._display_readiness.time.monotonic") as clock,
        patch(
            "punt_lux.service._hub_display_probe.HubDisplayProbe.connected",
            autospec=True,
        ) as hub,
    ):
        clock.return_value = 0
        ready = DisplayReadiness(
            RestartAttempt(DISPLAY_SPEC, 501, time.time(), 30), paths
        )
        hub.side_effect = ConnectionRefusedError("connection refused")
        assert not ready.observe(502)
        clock.return_value = 5
        hub.side_effect = None
        hub.return_value = "dial"
        assert not ready.observe(502)
        clock.return_value = 8
        assert ready.observe(502)


def test_connecting_at_28_seconds_cannot_finish_before_timeout(
    paths: MagicMock,
) -> None:
    with (
        patch("punt_lux.service._display_readiness.time.monotonic") as clock,
        patch(
            "punt_lux.service._hub_display_probe.HubDisplayProbe.connected",
            return_value="dial",
        ),
    ):
        clock.return_value = 0
        ready = DisplayReadiness(
            RestartAttempt(DISPLAY_SPEC, 501, time.time(), 30), paths
        )
        clock.return_value = 28
        assert not ready.observe(502)
        clock.return_value = 29.9
        assert not ready.observe(502)
        clock.return_value = 30
        with pytest.raises(ReadinessError, match="stability window"):
            ready.observe(502)


def test_polls_does_not_yield_at_the_deadline() -> None:
    now = 0.0

    def sleep(seconds: float) -> None:
        nonlocal now
        now += seconds

    with (
        patch(
            "punt_lux.service._display_readiness.time.monotonic",
            side_effect=lambda: now,
        ),
        patch("punt_lux.service._display_readiness.time.sleep", side_effect=sleep),
    ):
        assert len(list(DisplayReadiness.polls(1, 0.25))) == 3
        assert now == 1


def test_stale_stderr_is_omitted_and_current_tail_names_mtime(tmp_path: Path) -> None:
    log = tmp_path / ".punt-labs/lux/logs/luxd-display-stderr.log"
    log.parent.mkdir(parents=True)
    log.write_text("old monitor error")
    mtime = log.stat().st_mtime
    with patch("pathlib.Path.home", return_value=tmp_path):
        stale = DisplayRestartScope(
            RestartAttempt(DISPLAY_SPEC, 501, mtime + 1, 30), MagicMock()
        ).stderr_tail()
        fresh = DisplayRestartScope(
            RestartAttempt(DISPLAY_SPEC, 501, mtime, 30), MagicMock()
        ).stderr_tail()
    assert "omitted" in stale and "old monitor error" not in stale
    assert "old monitor error" in fresh
    assert f"mtime {mtime:.6f}" in fresh


@pytest.mark.parametrize(
    "pids,connections,expected_error",
    [
        ([502, None], [False], "exited before connecting to Hub"),
        ([502, None], [True], "exited after 3.0s connected to Hub"),
        ([502, 502], [True, True], None),
    ],
)
def test_restart_command_uses_the_full_stability_witness(
    paths: MagicMock,
    pids: list[int | None],
    connections: list[bool],
    expected_error: str | None,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monitor_error = "HelloImGui: could not use non existent monitor #0!"
    log = tmp_path / ".punt-labs/lux/logs/luxd-display-stderr.log"
    log.parent.mkdir(parents=True)
    log.write_text(monitor_error)
    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch(
            "punt_lux.service._display_restart_attempt.time.time",
            return_value=log.stat().st_mtime,
        ),
        patch("punt_lux.service._display_readiness.time.monotonic") as clock,
        patch("punt_lux.service._backends.pgrep_pid", side_effect=[501, *pids]),
        patch(
            "punt_lux.service._hub_display_probe.HubDisplayProbe.connected",
            side_effect=connections,
        ),
    ):
        clock.return_value = 0

        def polls() -> Iterator[None]:
            for tick in [0, 3]:
                clock.return_value = tick
                yield

        with patch.object(DisplayRestart, "_polls", side_effect=polls):
            restart = DisplayRestart(manager=MagicMock(), paths=paths)
            if expected_error is None:
                assert "pid 502" in restart.run()
            else:
                with pytest.raises(
                    DisplayRestartError, match=expected_error
                ) as failure:
                    restart.run()
                assert monitor_error in str(failure.value)
                assert monitor_error in caplog.text


def test_probe_cannot_turn_a_deadline_overrun_into_success(paths: MagicMock) -> None:
    with (
        patch("punt_lux.service._display_readiness.time.monotonic") as clock,
        patch(
            "punt_lux.service._hub_display_probe.HubDisplayProbe.connected",
            autospec=True,
        ) as hub,
    ):
        clock.return_value = 0
        ready = DisplayReadiness(
            RestartAttempt(DISPLAY_SPEC, 501, time.time(), 30), paths
        )
        clock.return_value = 29.9

        def slow_reply(probe: HubDisplayProbe) -> bool:
            pid, timeout = probe._pid, probe._timeout
            assert pid == 502
            assert timeout == pytest.approx(0.1)
            clock.return_value = 30.1
            return True

        hub.side_effect = slow_reply
        with pytest.raises(ReadinessError, match="within 30s"):
            ready.observe(502)


def test_timeout_without_hub_match_names_missing_witness(paths: MagicMock) -> None:
    with (
        patch("punt_lux.service._display_readiness.time.monotonic", return_value=0),
        patch(
            "punt_lux.service._hub_display_probe.HubDisplayProbe.connected",
            return_value=False,
        ),
    ):
        ready = DisplayReadiness(
            RestartAttempt(DISPLAY_SPEC, 501, time.time(), 30), paths
        )
        assert not ready.observe(502)
        with pytest.raises(ReadinessError, match="never connected to Hub"):
            ready.timeout()


def test_local_and_hub_probes_share_the_remaining_deadline(paths: MagicMock) -> None:
    with (
        patch("punt_lux.service._display_readiness.time.monotonic") as clock,
        patch(
            "punt_lux.service._readiness_probe.ReadinessProbe.local", autospec=True
        ) as local,
        patch(
            "punt_lux.service._hub_display_probe.HubDisplayProbe.connected",
            autospec=True,
        ) as hub,
    ):
        clock.return_value = 0
        ready = DisplayReadiness(
            RestartAttempt(DISPLAY_SPEC, 501, time.time(), 30), paths
        )
        clock.return_value = 29.8

        def local_probe(paths: MagicMock, pid: int, timeout: float) -> bool:
            assert pid == 502
            assert timeout == pytest.approx(30 - clock.return_value)
            clock.return_value += 0.05
            return True

        def hub_probe(probe: HubDisplayProbe) -> str:
            timeout = probe._timeout
            assert timeout == pytest.approx(30 - clock.return_value)
            clock.return_value += 0.05
            return "dial"

        local.side_effect = local_probe
        hub.side_effect = hub_probe
        assert not ready.observe(502)
        assert local.call_count == 2
        clock.return_value = 30
        with pytest.raises(ReadinessError, match="within 30s"):
            ready.observe(502)
        assert local.call_count == 2


def test_local_probe_time_cannot_age_the_preceding_hub_sample(paths: MagicMock) -> None:
    with (
        patch("punt_lux.service._display_readiness.time.monotonic") as clock,
        patch(
            "punt_lux.service._readiness_probe.ReadinessProbe.local", autospec=True
        ) as local,
        patch(
            "punt_lux.service._hub_display_probe.HubDisplayProbe.connected",
            return_value="dial",
        ),
    ):
        clock.return_value = 0
        ready = DisplayReadiness(
            RestartAttempt(DISPLAY_SPEC, 501, time.time(), 30), paths
        )
        assert not ready.observe(502)

        def local_probe(_paths: MagicMock, _pid: int, _timeout: float) -> bool:
            if local.call_count == 4:
                clock.return_value = 3.1
            return True

        local.side_effect = local_probe
        clock.return_value = 2.5
        assert not ready.observe(502)
        clock.return_value = 3.2
        assert ready.observe(502)


def test_reply_delivery_time_cannot_finish_the_window(paths: MagicMock) -> None:
    with (
        patch("punt_lux.service._display_readiness.time.monotonic") as clock,
        patch(
            "punt_lux.service._hub_display_probe.HubDisplayProbe.connected",
            autospec=True,
        ) as hub,
    ):
        clock.return_value = 0
        hub.return_value = "dial"
        ready = DisplayReadiness(
            RestartAttempt(DISPLAY_SPEC, 501, time.time(), 30), paths
        )
        assert not ready.observe(502)

        def delayed_reply(_probe: HubDisplayProbe) -> str:
            clock.return_value = 3.2
            return "dial"

        clock.return_value = 2.8
        hub.side_effect = delayed_reply
        assert not ready.observe(502)
        clock.return_value = 3.3
        hub.side_effect = None
        assert ready.observe(502)


def test_stderr_tail_surfaces_monitor_error_and_is_bounded(tmp_path: Path) -> None:
    path = tmp_path / ".punt-labs/lux/logs/luxd-display-stderr.log"
    path.parent.mkdir(parents=True)
    path.write_text(
        "old line\n" * 1000 + "HelloImGui: could not use non existent monitor #0!\n"
    )
    with patch("pathlib.Path.home", return_value=tmp_path):
        tail = DisplayRestartScope(
            RestartAttempt(DISPLAY_SPEC, 501, 0, 30), MagicMock()
        ).stderr_tail()
    assert "non existent monitor #0" in tail
    assert len(tail) <= 4200
    assert len(tail.splitlines()) <= 14


@pytest.mark.parametrize("content", [None, ""])
def test_unavailable_or_empty_stderr_does_not_mask_failure(
    tmp_path: Path, content: str | None
) -> None:
    with patch("pathlib.Path.home", return_value=tmp_path):
        if content is not None:
            path = tmp_path / ".punt-labs/lux/logs/luxd-display-stderr.log"
            path.parent.mkdir(parents=True)
            path.write_text(content)
        assert (
            DisplayRestartScope(
                RestartAttempt(DISPLAY_SPEC, 501, 0, 30), MagicMock()
            ).stderr_tail()
            == ""
        )


@pytest.mark.parametrize(
    "error",
    [
        ConnectionRefusedError("refused"),
        ConnectionResetError("reset"),
        ConnectionError("missing port file"),
        ConnectionError("HTTP 500"),
        ConnectionError("Hub does not report its Display dial; restart Hub"),
    ],
)
def test_transport_failure_resets_an_observed_window(
    paths: MagicMock, error: ConnectionError
) -> None:
    with (
        patch("punt_lux.service._display_readiness.time.monotonic") as clock,
        patch(
            "punt_lux.service._hub_display_probe.HubDisplayProbe.connected",
            autospec=True,
        ) as hub,
    ):
        clock.return_value = 0
        ready = DisplayReadiness(
            RestartAttempt(DISPLAY_SPEC, 501, time.time(), 30), paths
        )
        hub.return_value = "dial"
        assert not ready.observe(502)
        clock.return_value = 2
        hub.side_effect = error
        assert not ready.observe(502)
        clock.return_value = 3
        hub.side_effect = None
        assert not ready.observe(502)
        clock.return_value = 5.9
        assert not ready.observe(502)
        clock.return_value = 6
        assert ready.observe(502)


@pytest.mark.parametrize(
    "last_error", ["last reset", "Hub does not report its Display dial; restart Hub"]
)
def test_timeout_names_the_last_transport_error(
    paths: MagicMock, last_error: str
) -> None:
    with (
        patch("punt_lux.service._display_readiness.time.monotonic") as clock,
        patch(
            "punt_lux.service._hub_display_probe.HubDisplayProbe.connected",
            autospec=True,
        ) as hub,
    ):
        clock.return_value = 0
        ready = DisplayReadiness(
            RestartAttempt(DISPLAY_SPEC, 501, time.time(), 30), paths
        )
        hub.side_effect = ConnectionError("first refused")
        assert not ready.observe(502)
        hub.side_effect = ConnectionError(last_error)
        assert not ready.observe(502)
        clock.return_value = 30
        with pytest.raises(ReadinessError, match=last_error) as error:
            ready.observe(502)
        assert "first refused" not in str(error.value)


def test_live_pid_without_local_socket_names_the_missing_witness(
    paths: MagicMock,
) -> None:
    paths.is_running.return_value = False
    with patch("punt_lux.service._display_readiness.time.monotonic") as clock:
        clock.return_value = 0
        ready = DisplayReadiness(
            RestartAttempt(DISPLAY_SPEC, 501, time.time(), 30), paths
        )
        assert not ready.observe(502)
        clock.return_value = 30
        with pytest.raises(
            ReadinessError, match="pid 502 has no live owned local socket"
        ):
            ready.observe(502)


@pytest.mark.parametrize("remaining,expected_calls", [(1.0, 1), (2.0, 2)])
def test_pgrep_runs_only_when_its_fixed_timeout_fits(
    paths: MagicMock, remaining: float, expected_calls: int
) -> None:
    with (
        patch("punt_lux.service._display_readiness.time.monotonic") as clock,
        patch("punt_lux.service._backends.pgrep_pid") as pgrep,
    ):
        clock.return_value = 0
        pgrep.side_effect = [501, None]

        def polls() -> Iterator[None]:
            clock.return_value = 30 - remaining
            yield

        with (
            patch.object(DisplayRestart, "_polls", side_effect=polls),
            pytest.raises(DisplayRestartError, match="within 30s"),
        ):
            DisplayRestart(manager=MagicMock(), paths=paths).run()
        assert pgrep.call_count == expected_calls
