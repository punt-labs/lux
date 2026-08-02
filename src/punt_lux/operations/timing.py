"""Duration attestation for the Hub's mutating operations.

Every mutation a client asks for — a scene installed, a frame raised, the menu
replaced — is timed by the process that performs it and logged at INFO with the
operation's name, what it acted on, and how long it took::

    op render scene=beads-lux 14 ms

The wrapper sits at the facade boundary, so every surface that enters through
the facade — an MCP tool, a REST route, a library call — is attested without
repeating itself. Read-only queries are deliberately not timed: they are
frequent, they change nothing a user sees, and a line per query would bury the
mutations that a slow click has to be explained by.
"""

from __future__ import annotations

import functools
import logging
import time
from typing import TYPE_CHECKING, Self, final

from punt_lux.operations.models.common import OpError
from punt_lux.operations.models.display_write import FrameRaise
from punt_lux.operations.models.scene_results import SceneShown

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["OperationSubject", "Timed"]

logger = logging.getLogger(__name__)


@final
class OperationSubject:
    """What an operation acted on, as its duration line names it.

    A result already carries the identity of what it touched; this reads that
    identity out for the log rather than asking the caller to repeat it. A
    result that names nothing in particular — a clear, a menu replacement —
    reads as ``-`` so the line keeps its columns.
    """

    __slots__ = ()

    def of(self, result: object) -> str:
        """Return the log token for ``result``."""
        if isinstance(result, SceneShown):
            return f"scene={result.scene_id}"
        if isinstance(result, FrameRaise):
            return f"frame={result.frame_id}"
        if isinstance(result, OpError):
            return f"error={result.code}"
        return "-"


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
        """Return ``operation`` wrapped so every call logs how long it took."""

        @functools.wraps(operation)
        def _timed(*args: P.args, **kwargs: P.kwargs) -> R:
            started = self._clock()
            result = operation(*args, **kwargs)
            self.attest(result, self._clock() - started)
            return result

        return _timed

    def attest(self, result: object, elapsed: float) -> None:
        """Log one line: the operation, what it acted on, and its milliseconds."""
        logger.info(
            "op %s %s %d ms",
            self._name,
            OperationSubject().of(result),
            round(elapsed * 1000),
        )
