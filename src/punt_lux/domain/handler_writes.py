"""HandlerWrites -- the judge a handler's write to an element must pass first.

A handler that runs on the Hub patches the Hub's own copy of an element, and the one
place that decides whether such a write may be made is the store's write seam
(``WriteSeam.admit``). The seam opens this scope around every route to a write: it
fires an interaction's event inside :meth:`HandlerWrites.judged`, and it applies an
agent's own write inside it, so the observers that write wakes are judged too. Every
``Element.apply_patch`` made in the scope is shown to the judge before the element is
touched. A write outside the scope (a display's replica) meets no judge.

The judge is held in a context variable, so it follows the thread that fired the
event, and it is lifted while the judge itself runs: a judge that measures a write on
a copy would otherwise be judged in turn.

The scope is a plain context manager, not a generator one: a refusal is an exception
the judge raises inside it, and ``contextlib`` re-assigns the traceback of whatever
passes through a generator manager, which a frozen, slotted exception does not allow.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from types import TracebackType

    from punt_lux.domain.element_abc import Element

__all__ = ["HandlerWrites", "JudgedScope", "WriteJudge"]

# Raises to refuse the write; returns to admit it.
type WriteJudge = Callable[[Element, Mapping[str, object]], None]

# PY-TS-14 OK: absence is the state "no handler is running", so no write is judged.
_JUDGE: ContextVar[WriteJudge | None] = ContextVar("lux_handler_writes", default=None)


@final
class JudgedScope:
    """The span in which one judge is in force; leaving it restores the one before."""

    _judge: WriteJudge
    _token: Token[WriteJudge | None] | None  # PY-TS-14 OK: unset until entered
    __slots__ = ("_judge", "_token")

    def __new__(cls, judge: WriteJudge) -> Self:
        self = super().__new__(cls)
        self._judge = judge
        self._token = None
        return self

    def __enter__(self) -> None:
        self._token = _JUDGE.set(self._judge)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._token is not None:
            _JUDGE.reset(self._token)
            self._token = None


@final
class HandlerWrites:
    """The scope a Hub handler runs in, and the check each of its writes meets."""

    __slots__ = ()

    @staticmethod
    def judged(judge: WriteJudge) -> JudgedScope:
        """Return the scope in which every element patch is shown to ``judge`` first."""
        return JudgedScope(judge)

    @staticmethod
    def admit(element: Element, patch: Mapping[str, object]) -> None:
        """Show a patch to the judge in scope, if any; the judge raises to refuse it."""
        judge = _JUDGE.get()
        if judge is None:
            return
        token = _JUDGE.set(None)  # the judge's own writes, on a copy, are not judged
        try:
            judge(element, patch)
        finally:
            _JUDGE.reset(token)
