"""Distinguish a child's own exit from cancellation of the call that owned it.

Only the former carries a result for the caller. Cancellation says nothing about
the work: its exit status is the leash's kill signal, not a subprocess failure.
"""

from __future__ import annotations

from typing import Self, final

__all__ = ["ProcessCancelledError", "ProcessExit"]


@final
class ProcessExit:
    """What a child wrote and the status it exited with, as one value."""

    _returncode: int
    _stderr: str
    _stdout: str
    __slots__ = ("_returncode", "_stderr", "_stdout")

    def __new__(cls, stdout: str, stderr: str, returncode: int) -> Self:
        self = super().__new__(cls)
        self._stdout = stdout
        self._stderr = stderr
        self._returncode = returncode
        return self

    @property
    def stdout(self) -> str:
        """Everything the child wrote to its standard output."""
        return self._stdout

    @property
    def stderr(self) -> str:
        """Everything the child wrote to its standard error."""
        return self._stderr

    @property
    def returncode(self) -> int:
        """The status the child exited with."""
        return self._returncode

    @property
    def succeeded(self) -> bool:
        """Whether the child exited with status zero."""
        return self._returncode == 0

    def failure(self, limit: int) -> str:
        """Explain the failed exit with stderr, falling back to its status.

        At most ``limit`` characters of the child's own complaint; a child that
        said nothing is named by its exit status.
        """
        return self._stderr.strip()[:limit] or f"exit {self._returncode}"


class ProcessCancelledError(BaseException):
    """The call that started this child process was cancelled, so lux ended it.

    Not a failure of child process and not worth a message: nobody is waiting for the
    answer any more. It is a ``BaseException`` for the reason ``CancelledError``
    is: the many ``except Exception`` boundaries between the query and the call
    that asked for it exist to turn failures into messages, and none of them
    should mistake a call that was walked away from for one.
    """
