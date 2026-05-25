"""Declarative handler catalog — per-Element typed factories + decorators.

The agent ships a wire spec for each handler the Element should run; the
catalog publishes the bounded vocabulary the wire spec may name. The wire
decoder (``protocol.handler_decoder``) looks up the named factory in the
catalog for the Element kind being decoded, calls it with the declared
parameters, then wraps the result through each named decorator before
installing the typed ``Handler[E]`` on the Element via ``add_handler``.

The split between catalog (the inner what) and decorators (the outer how)
keeps the combinatorial surface bounded: ``N`` factories times ``M``
decorators yields ``N + M`` definitions, not ``N * M``.

The catalogs live here in ``domain`` because they are typed against domain
event classes; the decoder that consumes them lives in ``protocol`` because
it owns the wire shape. The dependency arrow stays inward — domain knows
nothing about wire dicts.
"""

from __future__ import annotations

from punt_lux.domain.handlers.button_catalog import ButtonHandlers
from punt_lux.domain.handlers.decorators import (
    DecoratorFactory,
    DecoratorRegistry,
    PublishDecorator,
    PublishSink,
)
from punt_lux.domain.handlers.dialog_catalog import DialogHandlers
from punt_lux.domain.handlers.verb_vocabulary import BoundVerb, VerbVocabulary

__all__ = [
    "BoundVerb",
    "ButtonHandlers",
    "DecoratorFactory",
    "DecoratorRegistry",
    "DialogHandlers",
    "PublishDecorator",
    "PublishSink",
    "VerbVocabulary",
]
