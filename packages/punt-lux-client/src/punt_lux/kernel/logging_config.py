"""Configure Lux entry-point diagnostics through punt-observe."""

from __future__ import annotations

import logging
import os
import signal
import traceback
from contextlib import contextmanager
from typing import TYPE_CHECKING, final

from punt_observe.logging import configure_logging as _configure_logging

from punt_lux.kernel.log_level import resolve_level

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from types import FrameType

logger = logging.getLogger(__name__)


@final
class _Diagnostics:
    @staticmethod
    def configure(tool: str, role: str, *, verbose: bool = False) -> None:
        """Configure a private durable log with an optional diagnostic override."""
        level, invalid = ("DEBUG", False) if verbose else resolve_level("INFO")
        _configure_logging(
            tool,
            role,
            level=level,
            stderr_level="DEBUG" if verbose else "WARNING",
        )
        if invalid:
            logger.warning("Invalid LUX_LOG_LEVEL; using INFO")

    @staticmethod
    def failure_details(error: Exception) -> str:
        """Describe the exception type and stack locations without its message."""
        frames = " -> ".join(
            f"{frame.f_code.co_name}:{line}"
            for frame, line in traceback.walk_tb(error.__traceback__)
        )
        return f"{type(error).__name__} ({frames})"

    @staticmethod
    def record_signal(number: int) -> None:
        """Record that this process received ``number`` and is about to stop."""
        logger.warning(
            "received %s (pid=%d, parent=%d)",
            signal.Signals(number).name,
            os.getpid(),
            os.getppid(),
        )

    @classmethod
    def _stop_on_signal(cls, number: int, _frame: FrameType | None) -> None:
        """Record the signal, then die by it as the default disposition would.

        A supervisor tells a death by signal from a failure exit; an exit status
        of 128 plus the signal is a failure to systemd's ``Restart=on-failure``.
        """
        cls.record_signal(number)
        signal.signal(number, signal.SIG_DFL)
        os.kill(os.getpid(), number)

    @classmethod
    def _log_default_signals(cls) -> Callable[[], None]:
        """Log SIGTERM and SIGHUP where the process would die without a trace.

        Only a signal still on the default disposition is taken over, and the
        process still dies by it. A daemon that installs its own handler records
        the signal itself.
        """
        previous = {
            number: signal.getsignal(number)
            for number in (signal.SIGTERM, signal.SIGHUP)
            if signal.getsignal(number) == signal.SIG_DFL
        }
        for number in previous:
            signal.signal(number, cls._stop_on_signal)

        def restore() -> None:
            for number, handler in previous.items():
                signal.signal(number, handler)

        return restore

    @classmethod
    @contextmanager
    def process(cls, role: str, name: str) -> Generator[None]:
        """Configure logging; record the start, every failure and how it exited.

        A process killed by SIGKILL cannot record anything; the process that sent
        it is the one that logs.
        """
        cls.configure("lux", role)
        logger.info("%s started (pid=%d, parent=%d)", name, os.getpid(), os.getppid())
        restore = cls._log_default_signals()
        outcome = "normal return"
        try:
            yield
        except SystemExit as stopped:
            outcome = f"exit {stopped.code}"
            raise
        except KeyboardInterrupt:
            outcome = "interrupt"
            raise
        except Exception as error:
            outcome = "error"
            logger.error("%s failed: %s", name, cls.failure_details(error))
            raise
        finally:
            restore()
            logger.info("%s exiting: %s (pid=%d)", name, outcome, os.getpid())


configure_logging = _Diagnostics.configure
failure_details = _Diagnostics.failure_details
process_diagnostics = _Diagnostics.process
record_signal = _Diagnostics.record_signal
