"""HandlerWrites -- the transaction a handler's writes to an element are made in.

A handler that runs on the Hub patches the Hub's own copy of an element, and the one
place that decides whether such a write may be made is the store's write seam
(``WriteSeam.admit``). The scope is opened around every route to a write:
``ResolvedInteraction.fire`` opens it around an interaction's handlers, and the seam
opens it around an agent's own write, so the observers that write wakes are judged
too. Every ``Element.apply_patch`` made in the scope is shown to the transaction in
force before the element is touched. A write outside the scope (a display's replica)
meets no judge.

An element that is about to change its own state without a patch (a filtered table
model's filter, a dialog's model) says so first, so the transaction checkpoints it
before it changes; and an element that is removed inside the scope is handed to the
transaction, which removes it once everything else stood, so a rollback has nothing
to put back in the store.

The transaction is held in a context variable, so it follows the thread that fired the
event, and it is lifted while its judge runs: a judge that measures a write on a copy
would otherwise be judged in turn.

The scope is a plain context manager: a refusal is an exception the judge raises
inside it, and it passes through untouched. The refusals are plain exception classes
too, so a generator manager elsewhere on their way out cannot break them.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import TYPE_CHECKING, Self, final

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from types import TracebackType

    from punt_lux.domain.element_abc import Element
    from punt_lux.domain.transaction_scope import TransactionScope

__all__ = ["HandlerWrites", "JudgedScope", "WriteJudge", "WriteRefusedError"]


class WriteRefusedError(Exception):
    """The judge refused a write: the transaction that made it rolls back.

    Raised by the judge before the element is touched. An observer fan-out lets it
    through after the other observers have run, so a batch that woke the observer
    never reports success for a write that was refused.
    """


# Raises to refuse the write; returns to admit it.
type WriteJudge = Callable[[Element, Mapping[str, object]], None]


# PY-TS-14 OK: absence is the state "no handler is running", so no write is judged.
_SCOPE: ContextVar[TransactionScope | None] = ContextVar(
    "lux_handler_writes", default=None
)


@final
class JudgedScope:
    """The span one transaction is in force in; leaving it restores the one before."""

    # PY-TS-14 OK: ``None`` is the scope with no transaction: it lifts the one in force.
    _scope: TransactionScope | None
    _token: Token[TransactionScope | None] | None  # PY-TS-14 OK: unset until entered
    __slots__ = ("_scope", "_token")

    def __new__(cls, scope: TransactionScope | None) -> Self:
        self = super().__new__(cls)
        self._scope = scope
        self._token = None
        return self

    def __enter__(self) -> None:
        self._token = _SCOPE.set(self._scope)

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        if self._token is not None:
            _SCOPE.reset(self._token)
            self._token = None


@final
class HandlerWrites:
    """The scope a Hub handler runs in, and the messages an element sends to it."""

    __slots__ = ()

    @staticmethod
    def judged(scope: TransactionScope) -> JudgedScope:
        """Return the scope in which ``scope`` is the transaction every write meets."""
        return JudgedScope(scope)

    @staticmethod
    def unjudged() -> JudgedScope:
        """Return the scope with no transaction in force: a copy is patched here."""
        return JudgedScope(None)

    @staticmethod
    def in_transaction() -> bool:
        """Return whether a transaction is in force on this thread."""
        return _SCOPE.get() is not None

    @staticmethod
    def admit(element: Element, patch: Mapping[str, object]) -> None:
        """Show a patch to the transaction in force, if any; it raises to refuse it."""
        scope = _SCOPE.get()
        if scope is None:
            return
        with JudgedScope(None):  # the judge's own writes, on a copy, are not judged
            scope.admit(element, patch)

    @staticmethod
    def will_derive(element: Element) -> None:
        """Tell the transaction in force, if any, ``element`` is about to change."""
        scope = _SCOPE.get()
        if scope is not None:
            scope.note_derivation(element)

    @staticmethod
    def defer_removal(element: Element) -> bool:
        """Hand ``element``'s removal to the transaction in force, if any."""
        scope = _SCOPE.get()
        if scope is None:
            return False
        scope.defer_removal(element)
        return True
