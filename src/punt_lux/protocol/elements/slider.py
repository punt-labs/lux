"""SliderElement — a numeric slider on the Element ABC.

Keyword-only ``__new__`` with ``abc_di_defaults`` sentinels on
``renderer_factory`` / ``emit``; the Display rebinds the real factory. The codec
body lives in ``slider_codec.py``. Because ``min`` / ``max`` are patchable, every
numeric invariant is checked at the element boundary — ``validate()`` before
render, a whole-element re-check after ``apply_patch`` — never per setter, via
the single ``_range_error_messages`` predicate.
"""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING, Literal, Self, cast, final

from punt_lux.domain.element_abc import Element
from punt_lux.domain.handlers.decorators import PublishSink
from punt_lux.domain.interaction import ValueChanged
from punt_lux.domain.remote_dispatch_spec import RemoteDispatchSpec
from punt_lux.domain.validation import ValidationError
from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.patch_field import PatchField
from punt_lux.protocol.elements.slider_codec import JsonSliderDecoder, JsonSliderEncoder
from punt_lux.protocol.raising_publish_sink import RaisingPublishSink
from punt_lux.protocol.standalone_slider_handler import (
    build_standalone_slider_handler_decoder,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["SliderElement"]

# printf default per variant: %d for the integer slider (ImGui slider_int), %.1f float.
_DEFAULT_FORMATS: dict[bool, str] = {False: "%.1f", True: "%d"}


@final
class SliderElement(Element):
    """A numeric slider on the Element ABC.

    PY-TS-14 OK: ``tooltip`` stays ``str | None`` — absence is the documented
    contract for no tooltip. The ``format`` *parameter* is ``str | None`` (``None``
    means "use the variant default"), but the stored ``_format`` is always a
    concrete ``str``. ``integer`` is a genuine two-state flag, not a deferred type.
    """

    _id: str
    _label: str
    _value: float
    _min: float
    _max: float
    _format: str
    _integer: bool
    _tooltip: str | None
    _kind: Literal["slider"]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory = RAISING_FACTORY,
        emit: Emit = NO_EMIT,
        id: str,
        label: str = "",
        value: float = 0.0,
        min: float = 0.0,
        max: float = 100.0,
        format: str | None = None,  # None -> variant default (_DEFAULT_FORMATS)
        integer: bool = False,
        tooltip: str | None = None,
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._label = label
        self._value = value
        self._min = min
        self._max = max
        self._format = format if format is not None else _DEFAULT_FORMATS[integer]
        self._integer = integer
        self._tooltip = tooltip
        self._kind = "slider"
        return self

    # -- read-only accessors (the wire-facing surface) ----------------------

    @property
    def id(self) -> str:
        """Return the slider's stable identity within its enclosing Scene."""
        return self._id

    @property
    def kind(self) -> Literal["slider"]:
        """Return the wire discriminator — always ``"slider"``."""
        return self._kind

    @property
    def label(self) -> str:
        """Return the visible slider label."""
        return self._label

    @property
    def value(self) -> float:
        """Return the current thumb value."""
        return self._value

    @property
    def min(self) -> float:
        """Return the low end of the slider range."""
        return self._min

    @property
    def max(self) -> float:
        """Return the high end of the slider range."""
        return self._max

    @property
    def format(self) -> str:
        """Return the printf conversion ImGui uses to label the value."""
        return self._format

    @property
    def integer(self) -> bool:
        """Return whether the slider renders the integer (``slider_int``) variant."""
        return self._integer

    @property
    def action(self) -> Literal["changed"]:
        """Return the input action name — always ``"changed"``."""
        return "changed"

    @property
    def tooltip(self) -> str | None:
        """Return the hover-tooltip text, or None for no tooltip."""
        return self._tooltip

    # -- patch-path setters -------------------------------------------------
    # Each only coerces its field; the numeric invariants are re-checked once
    # for the whole element in ``apply_patch``, never per setter.

    def _set_value(self, value: object) -> None:
        self._value = PatchField("value").as_number(value)

    def _set_min(self, value: object) -> None:
        self._min = PatchField("min").as_number(value)

    def _set_max(self, value: object) -> None:
        self._max = PatchField("max").as_number(value)

    def _set_format(self, value: object) -> None:
        self._format = PatchField("format").as_str(value)

    def _set_label(self, value: object) -> None:
        self._label = PatchField("label").as_str(value)

    def _set_integer(self, value: object) -> None:
        self._integer = PatchField("integer").as_bool(value)

    def _set_tooltip(self, value: object) -> None:
        self._tooltip = PatchField("tooltip").as_optional_str(value)

    def apply_patch(self, patch: Mapping[str, object]) -> Self:
        """Apply a field patch atomically, re-checking the invariants at the boundary.

        The base setter loop rolls back on a coercion ``TypeError``; a
        whole-element re-check then rolls the whole patch back if the final state
        is invalid — so a combined ``{"value": 150, "max": 200}`` is accepted.
        """
        snapshot = dict(vars(self))
        super().apply_patch(patch)
        messages = self._range_error_messages()
        if messages:
            vars(self).clear()
            vars(self).update(snapshot)
            raise ValueError(messages[0])
        return self

    def _remote_dispatch_specs(self) -> tuple[RemoteDispatchSpec, ...]:
        """Return the value-changed bucket's spec under the fixed 'changed' action."""
        return (RemoteDispatchSpec(ValueChanged, self.action, "value_changed"),)

    # -- validation (DES-039) ----------------------------------------------

    def _numeric_fields(self) -> tuple[tuple[str, float], ...]:
        """Return the ``(name, value)`` pairs the numeric predicates scan."""
        return (("value", self._value), ("min", self._min), ("max", self._max))

    def _range_error_messages(self) -> tuple[str, ...]:
        """Return finiteness, integrality, and bounds errors — the shared predicate.

        Non-finite values report alone: a ``NaN`` breaks ImGui's slider and the
        value-equality reconciliation (``NaN != NaN``), so integrality or bounds
        errors against it are noise. Once finite, the two report together.
        """
        nonfinite = tuple(
            f"{name} must be finite, got {v!r}"
            for name, v in self._numeric_fields()
            if not math.isfinite(v)
        )
        if nonfinite:
            return nonfinite
        return self._integral_error_messages() + self._bounds_error_messages()

    def _integral_error_messages(self) -> tuple[str, ...]:
        """Return an error per non-integral field on the integer variant.

        ``slider_int`` truncates its bounds to ``int`` and commits whole numbers,
        so a non-integral bound or value would let a truncated commit fall
        outside the float range the Hub re-checks.
        """
        return (
            tuple(
                f"{name} ({v}) must be a whole number for an integer slider"
                for name, v in self._numeric_fields()
                if not float(v).is_integer()
            )
            if self._integer
            else ()
        )

    def _bounds_error_messages(self) -> tuple[str, ...]:
        """Return the inverted-range error alone, else any out-of-range error.

        An in-range check against an empty ``[min, max]`` would only add noise.
        """
        if self._min > self._max:
            return (f"min ({self._min}) must be <= max ({self._max})",)
        return (
            ()
            if self._min <= self._value <= self._max
            else (f"value ({self._value}) must be in [{self._min}, {self._max}]",)
        )

    def _format_invalid(self) -> bool:
        """Return whether ``format`` is not exactly one variant-matching conversion.

        Escaped ``%%`` is a literal percent; one real conversion must remain, from
        ``diouxX`` (integer slider) or ``eEfFgGaA`` (float). Width/precision are
        numeric only: a ``*`` makes ImGui's ``vsnprintf`` read an unsupplied
        vararg (only the value is passed), so ``%*f`` / ``%.*d`` fault.
        """
        specifiers = "diouxX" if self._integer else "eEfFgGaA"
        conversion = rf"%[-+ #0]*\d*(?:\.\d+)?[hlLjztq]*[{specifiers}]"
        literal = r"(?:[^%]|%%)*"
        return re.fullmatch(rf"{literal}{conversion}{literal}", self._format) is None

    def validate(self) -> tuple[ValidationError, ...]:
        """Return every range, finiteness, and format error at once (no fail-fast)."""
        messages = list(self._range_error_messages())
        if self._format_invalid():
            messages.append(
                f"format must be a single printf conversion, got {self._format!r}"
            )
        return tuple(ValidationError(self._id, self._kind, m) for m in messages)

    # -- codec delegators --------------------------------------------------

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonSliderEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> SliderElement:
        """Construct a SliderElement from a JSON-decoded mapping.

        Wires a noop-only handler decoder so a slider with no ``handlers`` decodes
        without a publish bus; a ``publish`` chain raises via ``RaisingPublishSink``.
        """
        decoder = JsonSliderDecoder(
            renderer_factory=RAISING_FACTORY,
            emit=NO_EMIT,
            element_cls=cls,
            handler_decoder=build_standalone_slider_handler_decoder(
                cast("PublishSink", RaisingPublishSink("SliderElement.from_dict")),
            ),
        )
        return decoder.decode(d)

    def widget_value(self) -> float:
        """Return the value SceneManager mirrors into WidgetState after a patch."""
        return self._value

    # -- introspection (Inspectable) ---------------------------------------

    def resolved_props(self) -> Mapping[str, object]:
        """Return the full resolved state, including defaulted fields."""
        return {
            "label": self._label,
            "value": self._value,
            "min": self._min,
            "max": self._max,
            "format": self._format,
            "integer": self._integer,
            "tooltip": self._tooltip,
        }
