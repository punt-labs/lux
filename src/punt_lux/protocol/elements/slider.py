"""SliderElement — a numeric slider on the Element ABC.

ABC subclass with keyword-only ``__new__``. The ``abc_di_defaults`` sentinels
on ``renderer_factory`` / ``emit`` keep direct construction compiling; the
Display binds the real factory in its post-receive rebind.

The codec body lives in ``slider_codec.py``; ``to_dict`` / ``from_dict`` stay
on the class as short delegators so the runtime-checkable
``domain.element.Element`` Protocol stays satisfied. The Element ABC /
``EventHandlerHost`` mixin owns the value-changed registry and dispatch; the
built-in ``_UpdateValueHandler`` (installed by the decoder) mirrors the
authoritative value on each commit.

Because ``min`` / ``max`` are patchable, the range invariant is checked at the
element boundary — ``validate()`` before render and a whole-element re-check
after ``apply_patch`` — not per setter. A per-setter raise would wrongly reject
a valid combined patch whose value arrives before its widening ``max``. One
shared predicate, ``_range_error_messages``, backs both boundary checks.
"""

from __future__ import annotations

import math
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


@final
class SliderElement(Element):
    """A numeric slider on the Element ABC.

    PY-TS-14 OK: ``tooltip`` stays ``str | None`` — absence is the documented
    contract for no tooltip. ``format`` stays ``str`` — a printf conversion is
    free-form text, not a finite enumeration, so there is no ``Literal`` to
    turn it into. ``integer`` stays ``bool`` — a genuine two-state flag that
    selects the ``slider_int`` render variant, not a deferred design decision.
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
        format: str = "%.1f",
        integer: bool = False,
        tooltip: str | None = None,
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._label = label
        self._value = value
        self._min = min
        self._max = max
        self._format = format
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

    # -- minimal setters for the scene patch path --------------------------
    #
    # The numeric setters only coerce — no per-setter range raise. The range
    # invariant is re-checked once for the whole element in ``apply_patch``.

    def _set_value(self, value: object) -> None:
        """Replace the thumb value (range re-checked at the element boundary)."""
        self._value = PatchField("value").as_number(value)

    def _set_min(self, value: object) -> None:
        """Replace the range low end (range re-checked at the element boundary)."""
        self._min = PatchField("min").as_number(value)

    def _set_max(self, value: object) -> None:
        """Replace the range high end (range re-checked at the element boundary)."""
        self._max = PatchField("max").as_number(value)

    def _set_format(self, value: object) -> None:
        """Replace the printf display format."""
        self._format = PatchField("format").as_str(value)

    def _set_label(self, value: object) -> None:
        """Replace the slider label."""
        self._label = PatchField("label").as_str(value)

    def _set_integer(self, value: object) -> None:
        """Replace the integer-variant flag."""
        self._integer = PatchField("integer").as_bool(value)

    def _set_tooltip(self, value: object) -> None:
        """Replace the tooltip text."""
        self._tooltip = PatchField("tooltip").as_optional_str(value)

    def apply_patch(self, patch: Mapping[str, object]) -> Self:
        """Apply a field patch atomically, re-checking the range at the boundary.

        Runs the base setter loop (which rolls back on a coercion ``TypeError``),
        then re-checks the whole-element range invariant. A combined patch is
        judged on its final state, not per setter — so ``{"value": 150,
        "max": 200}`` applied against a stale ``max`` of 100 is accepted, where a
        per-setter raise would wrongly reject the value before its ``max`` landed.
        A patch that leaves the element out of range is rolled back whole.
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

    def _range_error_messages(self) -> tuple[str, ...]:
        """Return the range/finiteness errors — the shared numeric predicate.

        Backs both ``validate()`` and the ``apply_patch`` boundary re-check, so
        the range invariant has one source of truth. Non-finite values are
        reported first: a ``NaN`` breaks both ImGui's slider and the
        value-equality reconciliation (``NaN != NaN``), so it must never install.
        Once finite, an inverted range is reported alone (an out-of-range check
        against an empty ``[min, max]`` would only add noise).
        """
        fields = (("value", self._value), ("min", self._min), ("max", self._max))
        nonfinite = tuple(
            f"{name} must be finite, got {v!r}"
            for name, v in fields
            if not math.isfinite(v)
        )
        if nonfinite:
            return nonfinite
        if self._min > self._max:
            return (f"min ({self._min}) must be <= max ({self._max})",)
        if not (self._min <= self._value <= self._max):
            return (f"value ({self._value}) must be in [{self._min}, {self._max}]",)
        return ()

    def _format_invalid(self) -> bool:
        """Return whether ``format`` is not a single printf conversion.

        A format with no ``%`` conversion, or more than one, can fault ImGui's
        C-side formatting; a minimal single-conversion check closes that crash
        class without parsing the whole printf grammar.
        """
        return not self._format or self._format.count("%") != 1

    def validate(self) -> tuple[ValidationError, ...]:
        """Return every range, finiteness, and format error at once (no fail-fast)."""
        errors = [
            ValidationError(self._id, self._kind, message)
            for message in self._range_error_messages()
        ]
        if self._format_invalid():
            errors.append(
                ValidationError(
                    self._id,
                    self._kind,
                    f"format must be a single printf conversion, got {self._format!r}",
                )
            )
        return tuple(errors)

    # -- codec delegators --------------------------------------------------

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonSliderEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> SliderElement:
        """Construct a SliderElement from a JSON-decoded mapping.

        Wires a noop-only handler decoder so a slider with no ``handlers``
        decodes without a publish bus; a ``publish`` decorator chain raises via
        ``RaisingPublishSink``.
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
