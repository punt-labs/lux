"""How a ``bd`` child ended: with an exit it chose, or because its call was cancelled.

The two are not the same kind of ending. A child that exited non-zero is ``bd``
telling lux something, and the user is shown what. A child lux ended because the
call that started it was cancelled said nothing: its exit status is lux's own
kill signal, and presenting that as a ``bd`` failure would show the user an error
for work they walked away from.
"""

from __future__ import annotations

from typing import Self, final

__all__ = ["BdCancelledError", "BdExit"]


@final
class BdExit:
    """What a ``bd`` child wrote and the status it exited with, as one value."""

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


class BdCancelledError(BaseException):
    """The call that started this ``bd`` was cancelled, so lux ended it.

    Not a failure of ``bd`` and not worth a message: nobody is waiting for the
    answer any more. It is a ``BaseException`` for the reason ``CancelledError``
    is: the many ``except Exception`` boundaries between the query and the call
    that asked for it exist to turn failures into messages, and none of them
    should mistake a call that was walked away from for one.
    """
