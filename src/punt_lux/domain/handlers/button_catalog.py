"""``ButtonHandlers`` — catalog of declarative handler factories for buttons.

Each entry is a typed factory returning ``Handler[ButtonClicked]``. The
wire decoder picks an entry by name, supplies the declarative parameters
the entry takes, and wraps the result through the decorator chain
before installing it on the constructed Element via ``add_handler``.

Two factories ship in PR 4:

- ``noop`` — a do-nothing inner handler. Used when the only side effect
  is the decorator chain (e.g., a button that just publishes a topic).
- ``call_model`` — invokes a parent-component model method bound at
  decode time. The parent's decoder resolves the wire verb string
  against the model's verb vocabulary and passes the resulting
  ``BoundVerb`` in; the agent never sees the model object.

``ButtonHandlers`` is a namespace, not an instantiable class — every
member is a ``@staticmethod`` whose return type is the typed handler
the ABC expects.

Handler factories return callable class instances (not closures) so the
resulting handlers survive native serialization — required for the
Hub-to-Display transport path where element trees cross the wire as
serialized Python objects.
"""

from __future__ import annotations

from typing import Self

from punt_lux.domain.event_protocol import Handler
from punt_lux.domain.handlers.verb_vocabulary import BoundVerb
from punt_lux.domain.interaction import ButtonClicked

__all__ = ["ButtonHandlers"]


class _NoopHandler:
    """Serializable no-op handler for ``ButtonClicked``."""

    def __call__(self, _event: ButtonClicked) -> None:
        return None


class _CallModelHandler:
    """Serializable handler that invokes a ``BoundVerb`` on click."""

    _verb: BoundVerb

    def __new__(cls, *, verb: BoundVerb) -> Self:
        self = super().__new__(cls)
        self._verb = verb
        return self

    def __reduce__(self) -> tuple[object, ...]:
        """Support native serialization for Hub-to-Display transport."""
        return (object.__new__, (type(self),), {"_verb": self._verb})

    def __setstate__(self, state: dict[str, object]) -> None:
        """Restore state after native deserialization."""
        for key, value in state.items():
            object.__setattr__(self, key, value)

    def __call__(self, _event: ButtonClicked) -> None:
        self._verb.invoke()


class ButtonHandlers:
    """Catalog of declarative handler factories for ``ButtonElement``."""

    @staticmethod
    def noop() -> Handler[ButtonClicked]:
        """Return a handler that does nothing.

        Used as the inner handler for clicks that exist only to fire
        decorator side effects (publish, log, etc.). A button that
        publishes a topic and does nothing else wraps ``noop()``.
        """
        return _NoopHandler()

    @staticmethod
    def call_model(verb: BoundVerb) -> Handler[ButtonClicked]:
        """Invoke the bound model verb resolved at decode time.

        The parent component's decoder resolves the wire verb string
        against the model's vocabulary and passes the resulting
        ``BoundVerb`` in. The handler captures the binding; the
        event itself carries no model reference.
        """
        return _CallModelHandler(verb=verb)
