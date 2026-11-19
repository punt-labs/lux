"""Arm SIGTERM only once runner_params exists."""

from __future__ import annotations

import signal
from unittest.mock import MagicMock, patch

from punt_lux.display.exit_signal import ExitSignal


class TestExitSignal:
    def test_sets_app_shall_exit_rather_than_raising(self) -> None:
        # A SystemExit raised from the handler would only unwind Python frames;
        # while the main thread is inside immapp.run()'s C++ loop it would never
        # be seen, and the process would limp until the supervisor's SIGKILL
        # grace window expired. app_shall_exit asks the loop
        # itself to stop, so before_exit cleanup still runs.
        runner_params = MagicMock()
        runner_params.app_shall_exit = False
        with patch("punt_lux.display.exit_signal.signal.signal"):
            exit_signal = ExitSignal(runner_params)

        exit_signal._handle(15, None)

        assert runner_params.app_shall_exit is True

    def test_arms_sigterm_on_construction(self) -> None:
        # Construction is the only opportunity to register the handler.
        runner_params = MagicMock()
        with patch("punt_lux.display.exit_signal.signal.signal") as sig:
            ExitSignal(runner_params)

        assert sig.call_args[0][0] == signal.SIGTERM
