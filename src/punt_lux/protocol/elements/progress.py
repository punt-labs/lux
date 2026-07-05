"""ProgressElement — a display-only progress bar on the Element ABC.

ABC subclass with keyword-only ``__new__``. Sentinel defaults on
``renderer_factory`` and ``emit`` (shared through ``abc_di_defaults``) keep
direct construction compiling; the Display binds the real factory in its
post-receive rebind. A progress bar is a leaf — no children, no handlers,
no interaction — so it overrides none of the render-template hooks.

The codec body lives in ``progress_codec.py`` (``JsonProgressEncoder`` /
``JsonProgressDecoder``); ``to_dict`` and ``from_dict`` remain on the class
as short delegators so the runtime-checkable ``domain.element.Element``
Protocol stays satisfied. ``validate()`` adds the ``[0, 1]`` + NaN semantic
check (DES-039) the legacy dataclass left to ImGui's visual clamp.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Literal, Self, cast

from punt_lux.domain.element_abc import Element
from punt_lux.domain.validation import ValidationError
from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.patch_field import PatchField
from punt_lux.protocol.elements.progress_codec import (
    JsonProgressDecoder,
    JsonProgressEncoder,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["ProgressElement"]


class ProgressElement(Element):
    """A progress bar: a fill ``fraction`` plus an optional overlay ``label``.

    PY-TS-14 OK: ``tooltip`` stays ``str | None`` — absence is the documented
    contract for no tooltip. ``fraction`` is a total ``float`` (default
    ``0.0``) and ``label`` a total ``str`` (default ``""``, the discriminated
    "no overlay" state), so neither needs an Optional.
    """

    _id: str
    _fraction: float
    _label: str
    _tooltip: str | None
    _kind: Literal["progress"]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory = RAISING_FACTORY,
        emit: Emit = NO_EMIT,
        id: str,
        fraction: float = 0.0,
        label: str = "",
        tooltip: str | None = None,
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._fraction = fraction
        self._label = label
        self._tooltip = tooltip
        self._kind = "progress"
        return self

    # -- read-only accessors (the wire-facing surface) ----------------------

    @property
    def id(self) -> str:
        """Return the element's stable identity within its enclosing Scene."""
        return self._id

    @property
    def kind(self) -> Literal["progress"]:
        """Return the wire discriminator — always ``"progress"``."""
        return self._kind

    @property
    def fraction(self) -> float:
        """Return the fill fraction the bar paints, in ``[0, 1]``."""
        return self._fraction

    @property
    def label(self) -> str:
        """Return the overlay text, or ``""`` for the percentage fallback."""
        return self._label

    @property
    def tooltip(self) -> str | None:
        """Return the hover-tooltip text, or ``None`` for no tooltip."""
        return self._tooltip

    # -- minimal setters for the scene patch path ---------------------------
    #
    # ``Element.apply_patch`` dispatches JSON-decoded values straight to these
    # setters, so each ``value`` arrives as ``object`` and PY-EH-1 demands
    # boundary validation before we assign to a narrowly-typed attribute.

    def _set_fraction(self, value: object) -> None:
        """Replace the fill fraction (used by ``Element.apply_patch``)."""
        self._fraction = PatchField("fraction").as_number(value)

    def _set_label(self, value: object) -> None:
        """Replace the overlay label (used by ``Element.apply_patch``)."""
        self._label = PatchField("label").as_str(value)

    def _set_tooltip(self, value: object) -> None:
        """Replace the tooltip text (used by ``Element.apply_patch``)."""
        self._tooltip = PatchField("tooltip").as_optional_str(value)

    # -- self-validation (DES-039) ------------------------------------------

    def validate(self) -> tuple[ValidationError, ...]:
        """Return an error when ``fraction`` is NaN or outside ``[0, 1]``.

        The decoder guarantees ``_fraction`` is a ``float`` at the boundary;
        NaN passes that type gate but is not a paintable fraction, so the
        component-appropriate range check lives here (aggregated by the tree
        walk and rejected before render).
        """
        f = self._fraction
        if math.isnan(f) or not (0.0 <= f <= 1.0):
            message = f"fraction must be in [0, 1], got {f!r}"
            return (ValidationError(self._id, self._kind, message),)
        return ()

    # -- codec delegators ---------------------------------------------------

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonProgressEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        """Construct a ProgressElement from a JSON-decoded mapping."""
        decoder = JsonProgressDecoder(
            renderer_factory=RAISING_FACTORY, emit=NO_EMIT, element_cls=cls
        )
        # ``element_cls=cls`` guarantees the decoder builds the concrete
        # subtype; the decoder's annotation is the supertype ProgressElement
        # so narrow back to ``Self`` for the Protocol contract.
        return cast("Self", decoder.decode(d))

    # -- introspection (Inspectable) ---------------------------------------

    def resolved_props(self) -> Mapping[str, object]:
        """Return the full resolved state, including defaulted fields."""
        return {
            "fraction": self._fraction,
            "label": self._label,
            "tooltip": self._tooltip,
        }
