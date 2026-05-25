"""``DialogHandlers`` — catalog of declarative handler factories for dialogs.

A composite Element kind (``DialogElement``) owns a private model with a
typed verb vocabulary. The dialog's child controllers (buttons) are wired
through this catalog: the parent's decoder resolves the verb string against
the model's vocabulary and passes the resulting ``BoundVerb`` into the
factory, which returns a typed ``Handler[ButtonClicked]`` (because the
controller IS a button).

This catalog is the dialog-side counterpart to ``ButtonHandlers``. The two
catalogs return the same ``Handler[ButtonClicked]`` shape because the
controllers are buttons; they differ in what the inner handler does.
``ButtonHandlers.call_model`` accepts any pre-resolved ``BoundVerb``;
``DialogHandlers.invoke_model`` is the dialog-flavored alias the dialog's
decoder reaches for when wiring child buttons against the dialog's model.

The two catalogs share an inner shape on purpose: a dialog is just a
composite that publishes a verb vocabulary; future composites
(``FormElement``, ``WizardElement``) get their own catalog the same way.
"""

from __future__ import annotations

from punt_lux.domain.event_protocol import Handler
from punt_lux.domain.handlers.verb_vocabulary import BoundVerb
from punt_lux.domain.interaction import ButtonClicked

__all__ = ["DialogHandlers"]


class DialogHandlers:
    """Catalog of declarative handler factories for ``DialogElement`` controllers."""

    @staticmethod
    def invoke_model(verb: BoundVerb) -> Handler[ButtonClicked]:
        """Return a handler that invokes the bound dialog-model verb.

        The dialog's decoder resolves the wire verb string against the
        ``DialogModel``'s vocabulary at decode time and passes the
        resulting ``BoundVerb`` in. The handler closure captures the
        binding; the event itself carries no model reference.
        """

        def _handler(_event: ButtonClicked) -> None:
            verb.invoke()

        return _handler
