"""Shared ``Handler[ValueChanged]`` implementations for the atomic input kinds.

The three atomic-value kinds — checkbox, combo, radio — each need two handlers
that were, before this module, triplicated per kind:

- ``ApplyPatchOnChange`` mirrors an interactive change onto the element's
  authoritative state. Checkbox patches ``value``; combo and radio patch
  ``selected``. The only per-kind difference is which field the patch names, so
  the class is parameterised by ``field`` and depends on nothing but
  ``Element.apply_patch`` and the ``ValueChanged`` payload.
- ``NoopValueHandler`` is the Null-Object stand-in (PY-DP-9) used when a
  standalone element's only side effect is a decorator such as ``publish``.

Both are pickled across the Hub/Display boundary: the Hub decodes the element,
installs the handler, and ``wrap_handlers_for_remote`` wraps the Display copy for
remote dispatch. ``ApplyPatchOnChange`` preserves ``__reduce__`` / ``__setstate__``
so its ``field`` and ``elem`` round-trip through the wire intact.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Literal, Self, final

from punt_lux.domain.handlers import DecoratorRegistry
from punt_lux.protocol.handler_decoder import FactoryRegistry, HandlerDecoder
from punt_lux.tracing import trace

if TYPE_CHECKING:
    from punt_lux.domain.element_abc import Element
    from punt_lux.domain.event_protocol import Handler
    from punt_lux.domain.handlers.decorators import PublishSink
    from punt_lux.domain.interaction import ValueChanged

__all__ = [
    "ApplyPatchOnChange",
    "NoopValueHandler",
    "build_standalone_value_handler_decoder",
]

# The atomic-value field an interactive change patches: the boolean ``value`` of
# a checkbox, or the integer ``selected`` index of a combo or radio.
type ChangedField = Literal["value", "selected"]


@final
class ApplyPatchOnChange:
    """Serializable handler that mirrors an interactive change onto element state.

    On the Hub side this runs when ``ValueChanged`` fires — updating the
    authoritative field named by ``field`` via ``apply_patch``. On the Display
    side, ``wrap_handlers_for_remote`` wraps it in a ``RemoteDispatchGroup`` that
    sends the interaction to the Hub instead of mutating locally.
    """

    _elem: Element
    _field: ChangedField

    def __new__(cls, elem: Element, *, field: ChangedField) -> Self:
        self = super().__new__(cls)
        self._elem = elem
        self._field = field
        return self

    def __reduce__(self) -> tuple[object, ...]:
        return (object.__new__, (type(self),), self._state())

    def __setstate__(self, state: Mapping[str, object]) -> None:
        for key, value in state.items():
            object.__setattr__(self, key, value)

    def _state(self) -> dict[str, object]:
        return {"_elem": self._elem, "_field": self._field}

    @trace
    def __call__(self, event: ValueChanged) -> None:
        self._elem.apply_patch({self._field: event.value})


@final
class NoopValueHandler:
    """Serializable no-op handler for ``ValueChanged`` (Null Object, PY-DP-9)."""

    __slots__ = ()

    def __call__(self, _event: ValueChanged) -> None:
        return None


def build_standalone_value_handler_decoder(
    sink: PublishSink,
) -> HandlerDecoder[ValueChanged]:
    """Return the ``HandlerDecoder`` for a standalone atomic-value element.

    A checkbox, combo, or radio without a parent composite model has no verb
    vocabulary, so the explicit factory registry contains only ``noop``. The
    built-in state-sync handler (``ApplyPatchOnChange``) is installed directly by
    the kind's decoder so the element keeps its value mirrored even when the wire
    JSON declares no handlers. The decorator registry binds to ``sink``.
    """
    factories: FactoryRegistry[ValueChanged] = FactoryRegistry()

    def _build_noop(_params: Mapping[str, object]) -> Handler[ValueChanged]:
        return NoopValueHandler()

    factories.register("noop", _build_noop)
    decorators = DecoratorRegistry(sink=sink)
    return HandlerDecoder(factories=factories, decorators=decorators)
