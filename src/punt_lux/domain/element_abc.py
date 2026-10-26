"""Element ABC: the fixed ``render()`` skeleton + four step hooks.

The ABC carries:

- ``render()`` — the never-overridden template skeleton (``_begin`` →
  ``_paint_self`` → ``_render_children`` → ``_end``). Each step is an
  overridable hook with a default; a leaf and a plain box override none.
- ``_children()`` — hook composites override to return their children.
- ``renderer_factory`` + ``emit`` — set at construction. Off the display
  tier the factory is the fail-loud ``RaisingRendererFactory`` sentinel;
  the Display rebinds the real factory via ``bind_renderer_factory``.
- ``apply_patch()`` — walks a patch dict calling ``_set_<key>`` per entry.
- The event handler registry + remote dispatch come from the
  ``EventHandlerHost`` mixin, kept separate so render and dispatch each
  stay one responsibility.
- The property-observer surface (``add_observer`` / ``mark_removed``) lets
  parent composites react to a child being removed.

``domain.element.Element`` (Protocol) is the structural contract for wire
dataclasses; this ABC is the behavioral contract for the ABC kinds.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar, Self

from punt_lux.domain.element_checkpoint import ElementCheckpoint
from punt_lux.domain.event_handler_host import EventHandlerHost
from punt_lux.domain.handler_writes import HandlerWrites
from punt_lux.domain.property_observers import PropertyObservers

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping

    from punt_lux.domain.event_protocol import Event, Handler
    from punt_lux.domain.observer_state import ObserversCheckpoint, StatefulObserver
    from punt_lux.domain.validation import ValidationError
    from punt_lux.protocol.renderer import Emit, Renderer, RendererFactory

__all__ = ["Element"]


class Element(EventHandlerHost, ABC):
    """Domain core for the ABC element kinds.

    Subclasses add fields and (optionally) behavior methods. They do NOT
    override ``render()`` — Composite + the template handle it. Composites
    override ``_children()`` to return their children tuple; leaves
    inherit the empty default. Event registration and dispatch come from
    the ``EventHandlerHost`` mixin.

    A kind whose setters depend on one another names the keys that must run first in
    ``_SETTER_PRIORITY``; every other key follows in the caller's order.
    """

    _SETTER_PRIORITY: ClassVar[tuple[str, ...]] = ()
    _renderer_factory: RendererFactory
    _emit: Emit
    _handlers: dict[type[Event], list[Handler[Event]]]
    _removed: bool
    _observers: PropertyObservers
    _children_tuple: tuple[Element, ...]

    def __init_subclass__(cls, **kwargs: object) -> None:
        """Refuse a kind whose ``_SETTER_PRIORITY`` names a key it has no setter for.

        ``_in_setter_order`` skips a priority key the patch lacks, so a misspelt one
        would be ignored for ever and the ordering it was written to guarantee would
        silently be lost.
        """
        super().__init_subclass__(**kwargs)
        unset = [
            k
            for k in cls._SETTER_PRIORITY
            if not callable(getattr(cls, f"_set_{k}", None))
        ]
        if unset:
            msg = f"{cls.__name__}._SETTER_PRIORITY names {unset} with no _set_<key>"
            raise TypeError(msg)

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
    ) -> Self:
        self = super().__new__(cls)
        self._renderer_factory = renderer_factory
        self._emit = emit
        self._handlers = {}
        self._removed = False
        self._observers = PropertyObservers()
        self._children_tuple = ()
        return self

    def __reduce__(self) -> tuple[object, ...]:
        """Support native serialization for Hub-to-Display transport.

        Returns a (callable, args, state) triple so the deserializer
        can reconstruct via ``object.__new__`` (bypassing the ABC's
        keyword-only ``__new__``) then restore state via ``__setstate__``.

        Hub-side bookkeeping (``_observers``) contains closures that
        reference ``HubDisplay`` and cannot survive serialization. The
        Display is a replica — it does not need Hub observers. Handlers
        are preserved so ``wrap_handlers_for_remote`` can wrap them on
        the Display side.
        """
        state = {k: v for k, v in self.__dict__.items() if k != "_observers"}
        return (object.__new__, (type(self),), state)

    def __setstate__(self, state: dict[str, object]) -> None:
        """Restore instance state after native deserialization."""
        for key, value in state.items():
            object.__setattr__(self, key, value)
        object.__setattr__(self, "_observers", PropertyObservers())

    @property
    @abstractmethod
    def id(self) -> str:
        """Return the element's stable identity within its enclosing Scene."""

    def render(self) -> None:
        """Fixed template skeleton over four step hooks. NEVER overridden.

        Runs ``_begin`` → ``_paint_self`` → ``_render_children`` → ``_end``;
        ``_end`` runs in a ``finally`` so an opened ImGui surface stays
        balanced even if a paint or a child ``render`` raises. Off the display
        tier the factory is the fail-loud sentinel until rebound on the Display.
        """
        renderer = self._renderer_factory(self)
        opened = self._begin(renderer)
        try:
            if opened:
                self._paint_self(renderer)
                self._render_children(renderer)
        finally:
            self._end(renderer, opened=opened)

    def _begin(self, renderer: Renderer) -> bool:
        """Open this node's surface; return whether the inner steps run.
        Default: delegate to the renderer's ``begin`` — a leaf renderer
        returns True (nothing to open), a container renderer opens its
        surface and may report it hidden."""
        return renderer.begin()

    def _paint_self(self, renderer: Renderer) -> None:
        """Paint this node's own body. Default: delegate to the renderer.
        A pure container's renderer ``paint`` is a no-op."""
        renderer.paint()

    def _render_children(self, renderer: Renderer) -> None:
        """Paint the children between ``_begin`` and ``_end``. Default:
        recurse ``_children()``; a leaf paints nothing."""
        _ = renderer
        for child in self._children():
            child.render()

    def _end(self, renderer: Renderer, *, opened: bool) -> None:
        """Close this node's surface. Default: delegate to the renderer's
        ``end`` — a leaf renderer's ``end`` is a no-op, a container renderer
        closes only what ``opened`` says it opened."""
        renderer.end(opened=opened)

    def _children(self) -> tuple[Element, ...]:
        """Return this node's children — the render walk paints these.

        Backed by ``_children_tuple``: a composite populates it (in its
        constructor or a decoder seam) and a leaf leaves it empty. A kind
        whose children are computed rather than stored may still override
        this hook.
        """
        return self._children_tuple

    def bind_renderer_factory(self, factory: RendererFactory) -> None:
        """Rebind the renderer factory on this element and its subtree.

        Elements arrive off the wire carrying the sentinel factory (pickle
        preserves the constructing tier's). The Display calls this after
        receiving an element so ``render()`` resolves a real renderer.
        Recurses into ``_children()`` so a dialog and its buttons are
        rebound in one call.
        """
        self._renderer_factory = factory
        for child in self._children():
            child.bind_renderer_factory(factory)

    def validate(self) -> tuple[ValidationError, ...]:
        """Return this element's own validation errors.

        Sensible leaf default: no errors. Each kind overrides this to
        check what is *component-appropriate* for its widget. The tree
        walk calls this on every element and accumulates the results.
        """
        return ()

    def child_elements(self) -> tuple[Element, ...]:
        """Return direct children for the validation walk.

        Public bridge onto the protected ``_children()`` hook so the
        hierarchy-walking collector can recurse without reaching into
        renderer-facing internals. Composites get the right answer for
        free by populating ``_children_tuple``.
        """
        return self._children()

    def remove_child(self, child: Element) -> None:
        """Physically remove a direct child so the render stops painting it.

        Rebinds ``_children_tuple`` to exclude ``child`` by identity, so the
        render walk over ``_children()`` no longer paints it — keeping the
        Display's replica consistent with the Hub store (a removed element is
        gone from both, never a lingering node flagged removed but still
        rendered). Removing a child a node does not hold is a no-op; a leaf,
        whose tuple is always empty, is unaffected.
        """
        self._children_tuple = tuple(c for c in self._children_tuple if c is not child)

    def apply_patch(self, patch: Mapping[str, object]) -> Self:
        """Apply a field patch in place, atomically, returning ``self``.

        Dispatch each ``(key, value)`` to ``_set_{key}(value)``. All-or-nothing:
        setters run in dict order, so the state is snapshotted first and restored
        if any setter raises, then the error re-raised for the caller to handle —
        one base rollback for every kind, so per-setter self-restore is
        unnecessary.

        Observer notifications are *deferred to commit*: a setter records which
        property changed (via ``_notify_observers``) into a per-patch buffer, and
        the observers fire only after every key has succeeded. A later key failing
        rolls back the element and fires nothing, so an observer's own state (a
        bound ``FilteredTableModel``'s selection) never reflects a setter that failed.
        Each distinct property fires once even if several setters flag it (e.g. a
        patch that sets both ``rows`` and ``selected_row_ids``).

        That is the whole of this method's atomicity. Once the observers have been
        told, a write one of them makes that the judge refuses is raised out of here
        with this element already patched: undoing it, and every other write made
        under the same transaction, is the enclosing
        :class:`~punt_lux.domain.hub.batch_transaction.BatchTransaction`'s work, which
        checkpoints the element and the state its observers keep.

        A kind whose invariants span fields (a slider's value against its bounds)
        names them in ``_final_state_errors``. They are checked on the final state,
        after every setter and before the observers are told, so a patch that leaves
        the element invalid is refused with a ``ValueError`` and no observer hears it.

        A patch a Hub handler writes is first shown to the judge in scope
        (:class:`~punt_lux.domain.handler_writes.HandlerWrites`), which refuses it by
        raising: nothing has been touched when it does.
        """
        HandlerWrites.admit(self, patch)
        before = ElementCheckpoint(self)
        self._observers.begin()
        try:
            for key, value in self._in_setter_order(patch).items():
                getattr(self, f"_set_{key}")(value)
            errors = self._final_state_errors()
            if errors:
                raise ValueError(errors[0])
        except Exception:
            before.restore()
            self._observers.discard()
            raise
        self._observers.commit(self.id)  # each property once, in first-seen order
        return self

    def _final_state_errors(self) -> tuple[str, ...]:
        """Return why the element is invalid now, after every setter ran; else ``()``.

        The hook a kind overrides when its invariants span fields.
        """
        return ()

    def _in_setter_order(self, patch: Mapping[str, object]) -> dict[str, object]:
        """Return the patch's own items, the kind's priority keys first.

        A reorder only: the keys and values are the patch's, so a kind cannot change
        what the judge approved. The judge saw ``patch`` itself, before this.
        """
        first = {k: patch[k] for k in self._SETTER_PRIORITY if k in patch}
        return first | {k: v for k, v in patch.items() if k not in first}

    def announce_restored(self, props: Iterable[str]) -> None:
        """Tell the observers that keep no state that each of ``props`` is restored.

        A rollback's undo: an observer that keeps state of its own got it back from
        its checkpoint (``observer_checkpoint``) and is not told.
        """
        self._observers.announce_restored(props, self.id)

    def observer_checkpoint(self) -> ObserversCheckpoint:
        """Return the state of the observers that keep any, to restore on a rollback."""
        return self._observers.checkpoint()

    def add_observer(
        self,
        observer: Callable[[str], None],
        state: StatefulObserver | None = None,  # PY-TS-14 OK: most keep no state
    ) -> None:
        """Register a property-change observer, and the state it keeps if any.

        Parent composites use this to react to children flipping
        ``_removed`` (and, in future, ``_visible`` / ``_enabled``). An observer that
        derives state of its own passes itself as ``state`` so a rollback restores
        that state with the element.
        """
        self._observers.add(observer, state)

    @property
    def removed(self) -> bool:
        """Whether this Element has been marked removed from its scene."""
        return self._removed

    def mark_removed(self) -> None:
        """Flip ``_removed`` to True and notify observers. Idempotent.

        The single mechanism for marking any Element removed; all three
        removal paths (agent ``RemoveElement``, component self-dismiss,
        connection disconnect) reach it. The ``removed`` notification fans out
        through ``_notify_observers``.
        """
        if self._removed:
            return
        self._removed = True
        self._notify_observers("removed")

    def _notify_observers(self, prop: str) -> None:
        """Tell the observers that ``prop`` changed; buffered inside ``apply_patch``.

        The single fan-out point for property-change notifications (``removed``
        today; a table's ``selected_row_ids`` write-through, and future
        ``visible`` / ``enabled``): see :class:`PropertyObservers`.
        """
        self._observers.notify(prop, self.id)
