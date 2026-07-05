"""ProgressElement — a display-only progress bar on the Element ABC.

ABC subclass with keyword-only ``__new__``. Sentinel defaults on
``renderer_factory`` and ``emit`` (shared through ``abc_di_defaults``) keep
direct construction compiling; the Display binds the real factory in its
post-receive rebind. A progress bar is a leaf — no children, no handlers,
no interaction — so it overrides none of the render-template hooks.

The codec body lives in ``progress_codec.py`` (``JsonProgressEncoder`` /
``JsonProgressDecoder``); ``to_dict`` and ``from_dict`` remain on the class
as short delegators so the runtime-checkable ``domain.element.Element``
Protocol stays satisfied. One predicate, ``_fraction_out_of_range``, guards
both write paths so no unpaintable fraction reaches ImGui's visual clamp.
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

    def _set_fraction(self, value: object) -> None:
        """Coerce, range-check, then install the fraction; reject a bad patch."""
        previous = self._fraction
        self._fraction = PatchField("fraction").as_number(value)
        if self._fraction_out_of_range():
            self._fraction = previous  # a rejected patch installs nothing
            msg = f"fraction must be in [0, 1], got {value!r}"
            raise ValueError(msg)

    def _set_label(self, value: object) -> None:
        """Replace the overlay label (used by ``Element.apply_patch``)."""
        self._label = PatchField("label").as_str(value)

    def _set_tooltip(self, value: object) -> None:
        """Replace the tooltip text (used by ``Element.apply_patch``)."""
        self._tooltip = PatchField("tooltip").as_optional_str(value)

    def _fraction_out_of_range(self) -> bool:
        """Return whether ``fraction`` is NaN or outside ``[0, 1]``.

        NaN is caught explicitly though ``0.0 <= nan <= 1.0`` is already
        ``False`` — the sole source of the shared range invariant.
        """
        f = self._fraction
        return math.isnan(f) or not (0.0 <= f <= 1.0)

    def validate(self) -> tuple[ValidationError, ...]:
        """Return one error when ``fraction`` is NaN or outside ``[0, 1]``."""
        message = f"fraction must be in [0, 1], got {self._fraction!r}"
        return (
            (ValidationError(self._id, self._kind, message),)
            if self._fraction_out_of_range()
            else ()
        )

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonProgressEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        """Construct a ProgressElement from a JSON-decoded mapping."""
        decoder = JsonProgressDecoder(
            renderer_factory=RAISING_FACTORY, emit=NO_EMIT, element_cls=cls
        )
        # ``element_cls=cls`` guarantees the concrete subtype; the decoder's
        # annotation is the supertype, so narrow to ``Self`` for the Protocol.
        return cast("Self", decoder.decode(d))

    def resolved_props(self) -> Mapping[str, object]:
        """Return the full resolved state, including defaulted fields."""
        return {
            "fraction": self._fraction,
            "label": self._label,
            "tooltip": self._tooltip,
        }
