"""BeadsLoad — one ``bd`` run: what it read, and where lux's time around it went.

A board that took five seconds to arrive is not one fact but four, and only one
of them is ``bd``'s: lux spawned a process, waited on it, read what came back,
and turned it into rows. Each is measured separately here so the slow one names
itself, and every figure is one lux can actually take — the inside of ``bd`` is
not ours to instrument.

The counts belong for the same reason. A four-second wait for two hundred rows
and a four-second wait for twenty thousand are different problems.
"""

from __future__ import annotations

from typing import Self, final

from punt_lux.apps.bd_command import BdOutput
from punt_lux.apps.beads_result import BeadsResult, BeadsRows

__all__ = ["BeadsLoad"]

# Above this the byte count reads better in kilobytes than in digits.
_KILOBYTE = 1024


@final
class BeadsLoad:
    """A completed load: its result, and the figures behind how long it took."""

    _output: BdOutput
    _parse_ms: float
    _result: BeadsResult
    __slots__ = ("_output", "_parse_ms", "_result")

    def __new__(cls, result: BeadsResult, output: BdOutput, parse_ms: float) -> Self:
        self = super().__new__(cls)
        self._result = result
        self._output = output
        self._parse_ms = parse_ms
        return self

    @classmethod
    def failed(cls, failure: BeadsResult) -> Self:
        """A run that read nothing, and so has no figures worth reporting."""
        return cls(failure, BdOutput.none(), 0.0)

    @property
    def result(self) -> BeadsResult:
        """The issues that were read, or the reason none were."""
        return self._result

    def in_board_order(self) -> BeadsLoad:
        """Return the same run with its issues in the order every surface shows.

        Three stable passes: most recently updated, then by priority, then with
        whatever is in progress floated to the top. Ordering here rather than at
        each renderer keeps the command, the hook, and the menu click showing one
        board. A failed run has no order to put anything in and comes back as it
        was.
        """
        if not isinstance(self._result, BeadsRows):
            return self
        issues = self._result.issues
        issues.sort(key=lambda i: i.get("updated_at", ""), reverse=True)
        issues.sort(key=lambda i: i["priority"])
        issues.sort(key=lambda i: i["status"] != "in_progress")
        return BeadsLoad(BeadsRows.of(issues), self._output, self._parse_ms)

    def summary(self) -> str:
        """Where this run's time went, as the phrase beside its stage's figure."""
        return (
            f"spawn {self._output.spawn_ms:.0f}, "
            f"bd {self._output.bd_ms:.0f}, "
            f"parse {self._parse_ms:.0f}, "
            f"{self._size()}, {self._rows()} rows"
        )

    def _rows(self) -> int:
        """How many issues came through — none, when the run failed."""
        return len(self._result) if isinstance(self._result, BeadsRows) else 0

    def _size(self) -> str:
        """How much came back through the pipe, in the unit that reads best."""
        count = self._output.byte_count
        if count < _KILOBYTE:
            return f"{count} B"
        return f"{count / _KILOBYTE:.0f} kB"
