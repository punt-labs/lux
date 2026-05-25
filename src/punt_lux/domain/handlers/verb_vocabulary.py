"""``VerbVocabulary`` — typed action mapping a composite Element publishes.

A composite Element kind (``DialogElement``, future ``FormElement``) holds
a private model. The model publishes a typed verb vocabulary naming the
methods its child controllers may invoke against it. The decoder resolves
a wire verb string (``"confirm"``, ``"cancel"``) against the vocabulary
at decode time and binds the resolved verb into the child's handler; an
unknown verb raises ``ValueError`` immediately rather than at click time.

The Protocol is the structural contract every model satisfies. The
``BoundVerb`` helper carries the resolved (model, verb) pair to the
handler factory; the model's ``invoke`` method is the single dispatch
site, keeping ``_ACTIONS`` private to the model.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, Self, runtime_checkable

__all__ = ["BoundVerb", "VerbVocabulary"]


@runtime_checkable
class VerbVocabulary(Protocol):
    """Structural contract for composite-Element models that publish verbs.

    Two methods make up the contract: ``known_verbs`` reports the verbs
    the wire spec may name (used at decode time to fail loud on unknown
    verbs), and ``invoke`` dispatches a verb at runtime. The mapping
    backing both lives private to the implementing class.
    """

    def known_verbs(self) -> frozenset[str]:
        """Return the set of verbs ``invoke`` accepts."""
        ...

    def invoke(self, action: str) -> None:
        """Dispatch ``action`` against the model's vocabulary or raise."""
        ...


@dataclass(frozen=True, slots=True)
class BoundVerb:
    """A verb name resolved against a model's vocabulary.

    Carries the bound callable plus the original verb for diagnostics.
    Constructed by ``resolve_against`` so callers cannot forge an
    unbound verb.
    """

    _verb: str
    _bound: Callable[[], None]

    @classmethod
    def resolve_against(cls, model: VerbVocabulary, verb: str) -> Self:
        """Resolve ``verb`` against ``model``'s vocabulary or raise."""
        known = model.known_verbs()
        if verb not in known:
            msg = f"unknown verb: {verb!r} (expected one of {sorted(known)})"
            raise ValueError(msg)
        return cls(_verb=verb, _bound=lambda: model.invoke(verb))

    @property
    def verb(self) -> str:
        """Return the verb name the wire spec asked for."""
        return self._verb

    def invoke(self) -> None:
        """Invoke the bound model method."""
        self._bound()
