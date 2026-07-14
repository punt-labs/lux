"""RepushEffect — what the handler-driven dispatch re-push must reflect.

target.md's canonical replication rule: "when a handler mutates Hub-side
state, the Hub re-pushes the full scene tree to the Display." That re-push
leg lives inside ``_hub_interaction_dispatch`` (``client.show_async`` after
``element.fire``) and is distinct from the agent's own ``update`` re-push.
A ``RepushEffect`` asserts the leg fired *for real* by reading the Display
replica **after dispatch but before any agent update**:

- ``PropAfterDispatch`` — asserts the replica field after dispatch. Its
  proof strength depends on the scenario. The checkbox variant is the
  genuine re-push-carried-a-mutation proof: the value flips
  ``False``→``True`` only via the dispatch re-push (``_UpdateValueHandler``
  runs on the Hub copy, and the flipped value reaches the replica only if
  the leg fired). The button variant is weaker by design: it asserts an
  unchanged field on an element that persists in the replica from the
  original ``show``, so it proves only that the element survived the
  noop+publish dispatch unchanged — the assertion holds whether or not the
  dispatch re-push leg fired.
- ``RemovedAfterDispatch`` — a dialog's ``confirm`` runs ``mark_removed``
  on the Hub copy; the root-observer cascade drops it from ``HubDisplay``
  and the re-push carries the shrunken tree. The element is present before
  the click and absent after — proving removal travelled the dispatch
  re-push, not the agent's ``update``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, Self, runtime_checkable

from .inspection_view import InspectionView

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = ["PropAfterDispatch", "RemovedAfterDispatch", "RepushEffect"]


@runtime_checkable
class RepushEffect(Protocol):
    """The replica state the dispatch re-push must produce."""

    def assert_reflected(
        self,
        post_show: Mapping[str, object],
        post_dispatch: Mapping[str, object],
    ) -> None:
        """Assert the dispatch re-push reflected this effect."""
        ...


class PropAfterDispatch:
    """Assert ``element_id``'s prop reads ``value`` after the dispatch re-push.

    Covers both a handler that mutated the field (checkbox toggle) and one
    that left it untouched (a noop+publish button whose label is unchanged)
    — in both cases the element survived the re-push and reads the expected
    post-dispatch value.

    ``flipped`` makes the mutation proof self-contained: when set, the field
    must read a *different* value before the dispatch, so the post-dispatch
    match proves the re-push carried the change rather than the field already
    holding it. It stays ``False`` for the unchanged-field (button) variant,
    where pre and post are equal by design.
    """

    _element_id: str
    _field: str
    _value: object
    _flipped: bool

    def __new__(
        cls, *, element_id: str, field: str, value: object, flipped: bool = False
    ) -> Self:
        self = super().__new__(cls)
        self._element_id = element_id
        self._field = field
        self._value = value
        self._flipped = flipped
        return self

    def assert_reflected(
        self,
        post_show: Mapping[str, object],
        post_dispatch: Mapping[str, object],
    ) -> None:
        """Assert the re-pushed replica reads the expected field value."""
        if self._flipped:
            before = InspectionView(post_show).props(self._element_id)[self._field]
            assert before != self._value, (
                f"dispatch re-push: {self._element_id}.{self._field} must differ "
                f"before dispatch (was {before!r}) for the flip proof to hold"
            )
        props = InspectionView(post_dispatch).props(self._element_id)
        actual = props[self._field]
        assert actual == self._value, (
            f"dispatch re-push: {self._element_id}.{self._field} "
            f"expected {self._value!r}, got {actual!r}"
        )


class RemovedAfterDispatch:
    """Assert ``element_id`` was removed from the replica by the dispatch re-push.

    Present before the click, absent after — the handler's ``mark_removed``
    reached the Display only through ``_hub_interaction_dispatch``'s re-push
    leg, never the agent's ``update``.
    """

    _element_id: str

    def __new__(cls, element_id: str) -> Self:
        self = super().__new__(cls)
        self._element_id = element_id
        return self

    def assert_reflected(
        self,
        post_show: Mapping[str, object],
        post_dispatch: Mapping[str, object],
    ) -> None:
        """Assert the element was present pre-click and re-pushed away."""
        assert InspectionView(post_show).has(self._element_id), (
            f"dispatch re-push: {self._element_id} expected present before the click"
        )
        assert not InspectionView(post_dispatch).has(self._element_id), (
            f"dispatch re-push: {self._element_id} expected removed after the click"
        )
