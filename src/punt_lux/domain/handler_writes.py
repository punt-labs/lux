"""HandlerWrites -- the judge a handler's write to an element must pass first.

A handler that runs on the Hub patches the Hub's own copy of an element, and the one
place that decides whether such a write may be made is the store's write seam: it
fires the event inside :meth:`HandlerWrites.judged`, and every ``Element.apply_patch``
made while a handler runs is shown to the judge before the element is touched. A
write outside that scope (an agent's write, which has its own door, or a display's
replica) meets no judge.

The judge is held in a context variable, so it follows the thread that fired the
event, and it is lifted while the judge itself runs: a judge that measures a write on
a copy would otherwise be judged in turn.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING, final

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping

    from punt_lux.domain.element_abc import Element

__all__ = ["HandlerWrites", "WriteJudge"]

# Raises to refuse the write; returns to admit it.
type WriteJudge = Callable[[Element, Mapping[str, object]], None]

# PY-TS-14 OK: absence is the state "no handler is running", so no write is judged.
_JUDGE: ContextVar[WriteJudge | None] = ContextVar("lux_handler_writes", default=None)


@final
class HandlerWrites:
    """The scope a Hub handler runs in, and the check each of its writes meets."""

    __slots__ = ()

    @staticmethod
    @contextmanager
    def judged(judge: WriteJudge) -> Iterator[None]:
        """Run the body with every element patch shown to ``judge`` first."""
        token = _JUDGE.set(judge)
        try:
            yield
        finally:
            _JUDGE.reset(token)

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
