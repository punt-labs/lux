"""RecordingClickHandler — a picklable view-logic handler for the loop harness.

The harness needs the target element's Hub-side handler to do two
separable things on one interaction: run UI/view logic AND publish a
business topic (target.md §Event Models, loop invariant I6). The
``publish`` decorator carries the business half; this recorder carries
the view half. Registering it as a second handler in the element's event
bucket lets the harness assert the UI-handler mechanism fired
independently of the pub-sub mechanism.

The handler is a serializable class (not a closure) because the Hub's
authoritative element tree crosses the wire to build the Display replica;
its handler chain must survive native pickling, exactly like the shipped
``_CallModelHandler`` and ``_PublishWrappedHandler``.
"""

from __future__ import annotations

from typing import Self

__all__ = ["RecordingClickHandler"]


class RecordingClickHandler:
    """Record each fired event so the harness can assert the UI mechanism.

    The Hub fires this against its authoritative element copy; the test
    holds the same instance and reads ``fire_count`` to prove the
    element's handler dispatch (D21) ran — and ran exactly once. Only the
    count is kept, never the event object: the handler is re-serialized on
    every whole-scene re-push, and the ``ButtonClicked``/``ValueChanged``
    events are not designed to cross the wire. The Display replica gets a
    pickled copy that never fires (it is folded into a
    ``RemoteDispatchGroup`` that only sends).
    """

    _count: int

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._count = 0
        return self

    def __reduce__(self) -> tuple[object, ...]:
        """Support native serialization for Hub-to-Display transport."""
        return (object.__new__, (type(self),), {"_count": self._count})

    def __setstate__(self, state: dict[str, object]) -> None:
        """Restore state after native deserialization."""
        for key, value in state.items():
            object.__setattr__(self, key, value)

    def __call__(self, _event: object) -> None:
        """Count the fire — the view-logic side effect of the click."""
        self._count += 1

    @property
    def fire_count(self) -> int:
        """Return how many times the Hub fired this handler."""
        return self._count
