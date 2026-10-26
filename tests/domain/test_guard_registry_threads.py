"""GuardRegistry stays sound while guards are made and asked about on many threads."""

from __future__ import annotations

import threading
from typing import Self

from punt_lux.domain.hub.guard_registry import GuardRegistry
from tests.domain.display_double import Call


class _Guard:
    """A guard that holds nothing."""

    __slots__ = ("__weakref__",)

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def holds_here(self) -> bool:
        return False


def test_registering_while_other_threads_ask_never_corrupts_the_set() -> None:
    stop = threading.Event()

    def register() -> None:
        keep: list[_Guard] = []
        while not stop.is_set():
            guard = _Guard()
            keep.append(guard)
            GuardRegistry.register(guard)
            if len(keep) > 2000:
                keep.clear()  # the weak set also loses members mid-iteration

    def ask() -> None:
        while not stop.is_set():
            GuardRegistry.is_held()

    calls = [Call(register), Call(register), Call(ask), Call(ask)]
    stop.wait(1.5)
    stop.set()

    assert [call.wait(5.0) and call.error for call in calls] == [None] * 4
