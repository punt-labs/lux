"""The report ``lux doctor`` builds, and the three symbols every check answers with.

The symbols live here rather than in either caller because both need them: the
checks pick one per line, and the report counts by them. They were duplicated in
the two modules before, which is one definition too many for a vocabulary whose
whole job is that the two ends agree.
"""

from __future__ import annotations

from typing import Self, final

__all__ = ["FAIL", "OK", "OPTIONAL", "DoctorReport"]

OK = "✓"  # ✓
FAIL = "✗"  # ✗
OPTIONAL = "—"  # —


@final
class DoctorReport:
    """The lines ``doctor`` has collected and the tally it will exit on.

    The counting rule is the one thing here worth stating: a line counts as
    failed only when it is both a failure and required, so the advisory checks —
    fonts, the plugin, a display that simply is not up — colour the report without
    turning a working installation into a non-zero exit.
    """

    _lines: list[str]
    _passed: int
    _failed: int
    __slots__ = ("_failed", "_lines", "_passed")

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._lines = []
        self._passed = 0
        self._failed = 0
        return self

    def __call__(self, symbol: str, message: str, *, required: bool = True) -> None:
        """Record one check's outcome — the ``CheckReporter`` the checks are given."""
        self._lines.append(f"{symbol} {message}")
        if symbol == OK:
            self._passed += 1
        elif symbol == FAIL and required:
            self._failed += 1

    def render(self) -> str:
        """Return the report between rules, with the tally underneath.

        Returned rather than printed: the report knows what it says, and the
        command that asked for it owns the terminal it says it on.
        """
        rule = "=" * 40
        tally = f"{self._passed} passed, {self._failed} failed"
        return "\n".join([rule, *self._lines, rule, tally])

    @property
    def failed(self) -> int:
        """How many required checks failed — the command's exit code."""
        return self._failed
