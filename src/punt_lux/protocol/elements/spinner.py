"""SpinnerElement — an animated loading spinner on the Element ABC.

ABC subclass with keyword-only ``__new__``. Sentinel defaults on
``renderer_factory`` and ``emit`` (shared through ``abc_di_defaults``) keep
direct construction compiling; the Display binds the real factory in its
post-receive rebind. A spinner is a leaf — no children, no handlers, no
interaction — so it overrides none of the render-template hooks. It is not
vacuously valid: a non-positive ``radius`` renders a zero-size arc that
vanishes, so ``validate()`` reports it and the ``radius`` setter refuses it.

The codec body lives in ``spinner_codec.py`` (``JsonSpinnerEncoder`` /
``JsonSpinnerDecoder``); ``to_dict`` and ``from_dict`` remain on the class
as short delegators so the runtime-checkable ``domain.element.Element``
Protocol stays satisfied.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Literal, Self, cast

from punt_lux.domain.element_abc import Element
from punt_lux.domain.validation import ValidationError
from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.patch_field import PatchField
from punt_lux.protocol.elements.spinner_codec import (
    JsonSpinnerDecoder,
    JsonSpinnerEncoder,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["SpinnerElement"]


class SpinnerElement(Element):
    """An animated loading spinner: a ``radius``/``color`` disc plus a ``label``.

    PY-TS-14 OK: ``tooltip`` stays ``str | None`` — absence is the documented
    contract for no tooltip. ``label`` (default ``""``), ``radius`` (default
    ``16.0``), and ``color`` (default ``"#3399FF"``) are total, so none needs an
    Optional; the empty ``label`` is the discriminated "no caption" state.
    """

    _id: str
    _label: str
    _radius: float
    _color: str
    _tooltip: str | None
    _kind: Literal["spinner"]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory = RAISING_FACTORY,
        emit: Emit = NO_EMIT,
        id: str,
        label: str = "",
        radius: float = 16.0,
        color: str = "#3399FF",
        tooltip: str | None = None,
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._label = label
        self._radius = radius
        self._color = color
        self._tooltip = tooltip
        self._kind = "spinner"
        return self

    @property
    def id(self) -> str:
        """Return the element's stable identity within its enclosing Scene."""
        return self._id

    @property
    def kind(self) -> Literal["spinner"]:
        """Return the wire discriminator — always ``"spinner"``."""
        return self._kind

    @property
    def label(self) -> str:
        """Return the caption drawn beside the spinner, or ``""`` for none."""
        return self._label

    @property
    def radius(self) -> float:
        """Return the spinner disc radius in pixels."""
        return self._radius

    @property
    def color(self) -> str:
        """Return the spinner's stroke color as a hex string."""
        return self._color

    @property
    def tooltip(self) -> str | None:
        """Return the hover-tooltip text, or ``None`` for no tooltip."""
        return self._tooltip

    def _set_label(self, value: object) -> None:
        """Replace the caption (used by ``Element.apply_patch``)."""
        self._label = PatchField("label").as_str(value)

    def _set_radius(self, value: object) -> None:
        """Coerce and range-check the disc radius; a non-positive value raises.

        No self-restore — ``Element.apply_patch`` rolls the instance back.
        """
        self._radius = PatchField("radius").as_number(value)
        if self._radius_out_of_range():
            msg = f"radius must be positive, got {value!r}"
            raise ValueError(msg)

    def _set_color(self, value: object) -> None:
        """Replace the stroke color (used by ``Element.apply_patch``)."""
        self._color = PatchField("color").as_str(value)

    def _set_tooltip(self, value: object) -> None:
        """Replace the tooltip text (used by ``Element.apply_patch``)."""
        self._tooltip = PatchField("tooltip").as_optional_str(value)

    def _radius_out_of_range(self) -> bool:
        """Return whether ``radius`` is NaN or non-positive.

        A zero or negative radius paints a zero-size arc that vanishes; NaN is
        caught explicitly. The sole source of the shared positivity invariant.
        """
        r = self._radius
        return math.isnan(r) or r <= 0.0

    def validate(self) -> tuple[ValidationError, ...]:
        """Return one error when ``radius`` is NaN or non-positive."""
        message = f"radius must be positive, got {self._radius!r}"
        return (
            (ValidationError(self._id, self._kind, message),)
            if self._radius_out_of_range()
            else ()
        )

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonSpinnerEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        """Construct a SpinnerElement from a JSON-decoded mapping."""
        decoder = JsonSpinnerDecoder(
            renderer_factory=RAISING_FACTORY, emit=NO_EMIT, element_cls=cls
        )
        # ``element_cls=cls`` guarantees the concrete subtype; the decoder's
        # annotation is the supertype, so narrow to ``Self`` for the Protocol.
        return cast("Self", decoder.decode(d))

    def resolved_props(self) -> Mapping[str, object]:
        """Return the full resolved state, including defaulted fields."""
        return {
            "label": self._label,
            "radius": self._radius,
            "color": self._color,
            "tooltip": self._tooltip,
        }
