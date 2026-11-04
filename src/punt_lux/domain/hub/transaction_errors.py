"""TransactionErrors -- the ways code can misuse a batch transaction's judge.

Each is a rule the code broke, not a condition the data was in, so each is a
:class:`~punt_lux.domain.programmer_error.ProgrammerError`: no fan-out boundary an
observer or a handler runs under may log it and carry on.
"""

from __future__ import annotations

from typing import final

from punt_lux.domain.programmer_error import ProgrammerError

__all__ = ["JudgeReusedError", "WriteDuringRollbackError"]


@final
class JudgeReusedError(ProgrammerError):
    """A batch judge serves one batch: it was asked to settle a second time."""


@final
class WriteDuringRollbackError(ProgrammerError):
    """Something wrote, or asked to derive or remove, while a rollback was announcing.

    A rollback puts every element back as it was and only then tells the observers. A
    write an observer then made would move state past the restore, so the transaction
    cannot say it left everything as it found it.
    """
