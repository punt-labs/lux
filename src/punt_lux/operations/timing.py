"""Record selected Hub operation durations at the shared facade boundary."""

from __future__ import annotations

import functools
import time
from typing import TYPE_CHECKING, Self, final

from punt_lux.operations.models.common import OpError
from punt_lux.usage import record_operation

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["Timed"]


@final
class Timed:
    """A named mutation that attests its own duration when it runs.

    Applied as a decorator on a facade operation. ``clock`` is injected so a
    test can drive elapsed time directly instead of sleeping.
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
            started = self._clock()
            result = operation(*args, **kwargs)
            record_operation(
                self._name,
                (self._clock() - started) * 1000,
                failed=isinstance(result, OpError),
            )
            return result

        return _timed
