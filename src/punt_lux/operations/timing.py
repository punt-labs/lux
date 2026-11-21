"""Record selected Hub operation outcomes and durations at the facade boundary."""

from __future__ import annotations

import functools
import logging
import time
from typing import TYPE_CHECKING, Self, final

from punt_lux.operations.models.common import OpError
from punt_lux.usage import record_operation as record_usage

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["Timed"]

logger = logging.getLogger(__name__)


@final
class Timed:
    """A named mutation that attests its own outcome and duration when it runs.

    Applied as a decorator on a facade operation, so every surface (MCP, REST,
    in-process) leaves one INFO record per call naming the operation and its
    outcome, never the request's content. ``clock`` is injected so a test can
    drive elapsed time directly instead of sleeping.
    """

    _name: str
    _clock: Callable[[], float]
    __slots__ = ("_clock", "_name")

    def __new__(cls, name: str, clock: Callable[[], float] = time.perf_counter) -> Self:
        self = super().__new__(cls)
        self._name = name
        self._clock = clock
        return self

    def __call__[**P, R](self, operation: Callable[P, R]) -> Callable[P, R]:
        """Return ``operation`` wrapped so every call records how long it took."""

        @functools.wraps(operation)
        def _timed(*args: P.args, **kwargs: P.kwargs) -> R:
            start, outcome = self._clock(), "failed: raised"
            try:
                result = operation(*args, **kwargs)
                outcome = (
                    f"failed: {result.code}"
                    if isinstance(result, OpError)
                    else "succeeded"
                )
                return result
            finally:
                elapsed = (self._clock() - start) * 1000
                record_usage(self._name, elapsed, failed=outcome != "succeeded")
                logger.info(
                    "Hub operation %s %s (%.1f ms)", self._name, outcome, elapsed
                )

        return _timed
