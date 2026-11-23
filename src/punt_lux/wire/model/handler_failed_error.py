"""HandlerFailedError -- a handler raised in a transaction, so the event rolled back."""

from __future__ import annotations

from typing import final

__all__ = ["HandlerFailedError"]


@final
class HandlerFailedError(Exception):
    """A handler raised inside a transaction, so the whole event was rolled back.

    The handler's own exception is the ``__cause__``.
    """
