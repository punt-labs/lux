"""InputNumberElement — a numeric input with optional step and clamping bounds.

Keyword-only ``__new__`` with ``abc_di_defaults`` sentinels on ``renderer_factory``
/ ``emit`` (the Display rebinds the real factory); the codec body lives in
``input_number_codec.py``. Every numeric invariant is re-checked for the whole
element via the composed ``NumericInputChecks`` predicate — by ``validate`` before
render and by ``apply_patch`` — never per setter. ``min`` / ``max`` / ``step`` are
genuinely optional (``None`` = unbounded / no stepper).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, cast, final

from punt_lux.domain.element_abc import Element
from punt_lux.domain.handlers.decorators import PublishSink
from punt_lux.domain.interaction import ValueChanged
from punt_lux.domain.remote_dispatch_spec import RemoteDispatchSpec
from punt_lux.domain.validation import ValidationError
from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.input_number_codec import (
    JsonInputNumberDecoder,
    JsonInputNumberEncoder,
)
from punt_lux.protocol.elements.numeric_input_checks import NumericInputChecks
from punt_lux.protocol.elements.patch_field import PatchField
from punt_lux.protocol.raising_publish_sink import RaisingPublishSink
from punt_lux.protocol.standalone_input_number_handler import (
    build_standalone_input_number_handler_decoder,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["InputNumberElement"]

# printf default per variant: %d for the integer input (ImGui input_int), %.3f float.
_DEFAULT_FORMATS: dict[bool, str] = {False: "%.3f", True: "%d"}


@final
class InputNumberElement(Element):
    """A numeric input field on the Element ABC, with optional step and bounds.

    Each ``| None`` field is justified inline at its declaration (PY-TS-14):
    bounds/step are genuinely absent when unset, ``tooltip`` is optional UI state,
    and the ``format`` *parameter* resolves ``None`` to a concrete stored ``str``.
    """

    _id: str
    _label: str
    _value: float
    # PY-TS-14 OK: None = unbounded (no lower clamp / stepper floor).
    _min: float | None
    # PY-TS-14 OK: None = unbounded (no upper clamp / stepper ceiling).
    _max: float | None
    # PY-TS-14 OK: None = no stepper buttons.
    _step: float | None
    _format: str
    _integer: bool
    # PY-TS-14 OK: absence is the documented contract for no tooltip.
    _tooltip: str | None
    _kind: Literal["input_number"]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory = RAISING_FACTORY,
        emit: Emit = NO_EMIT,
        id: str,
        label: str = "",
        value: float = 0.0,
        min: float | None = None,
        max: float | None = None,
        step: float | None = None,
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
        self._step = step
        self._format = format if format is not None else _DEFAULT_FORMATS[integer]
        self._integer = integer
        self._tooltip = tooltip
        self._kind = "input_number"
        return self

    # -- read-only accessors (the wire-facing surface) ----------------------

    @property
    def id(self) -> str:
        """Return the input's stable identity within its enclosing Scene."""
        return self._id

    @property
    def kind(self) -> Literal["input_number"]:
        """Return the wire discriminator — always ``"input_number"``."""
        return self._kind

    @property
    def label(self) -> str:
        """Return the visible input label."""
        return self._label

    @property
    def value(self) -> float:
        """Return the current numeric value."""
        return self._value

    @property
    def min(self) -> float | None:
        """Return the lower clamp bound, or None for unbounded."""
        return self._min

    @property
    def max(self) -> float | None:
        """Return the upper clamp bound, or None for unbounded."""
        return self._max

    @property
    def step(self) -> float | None:
        """Return the stepper increment, or None for no stepper buttons."""
        return self._step

    @property
    def format(self) -> str:
        """Return the printf conversion ImGui uses to label the value."""
        return self._format

    @property
    def integer(self) -> bool:
        """Return whether the input renders the integer (``input_int``) variant."""
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
    # Each coerces its field; the invariants are re-checked whole-element in
    # ``apply_patch``, never per setter.

    def _set_value(self, value: object) -> None:
        self._value = PatchField("value").as_number(value)

    def _set_min(self, value: object) -> None:
        self._min = PatchField("min").as_optional_number(value)

    def _set_max(self, value: object) -> None:
        self._max = PatchField("max").as_optional_number(value)

    def _set_step(self, value: object) -> None:
        self._step = PatchField("step").as_optional_number(value)

    def _set_format(self, value: object) -> None:
        self._format = PatchField("format").as_str(value)

    def _set_label(self, value: object) -> None:
        self._label = PatchField("label").as_str(value)

    def _set_integer(self, value: object) -> None:
        self._integer = PatchField("integer").as_bool(value)

    def _set_tooltip(self, value: object) -> None:
        self._tooltip = PatchField("tooltip").as_optional_str(value)

    def apply_patch(self, patch: Mapping[str, object]) -> Self:
        """Apply a field patch atomically, re-checking every invariant at the boundary.

        The setter loop rolls back on a coercion ``TypeError``; the whole-element
        re-check (range *and* format) rolls the patch back on any invalid result.
        """
        snapshot = dict(vars(self))
        super().apply_patch(patch)
        messages = self._error_messages()
        if messages:
            vars(self).clear()
            vars(self).update(snapshot)
            raise ValueError(messages[0])
        return self

    def _remote_dispatch_specs(self) -> tuple[RemoteDispatchSpec, ...]:
        """Return the value-changed bucket's spec under the fixed 'changed' action."""
        return (RemoteDispatchSpec(ValueChanged, self.action, "value_changed"),)

    # -- validation --------------------------------------------------------

    def _checks(self) -> NumericInputChecks:
        """Return the range/format predicate over this element's current fields."""
        return NumericInputChecks(
            value=self._value,
            min=self._min,
            max=self._max,
            step=self._step,
            integer=self._integer,
            format=self._format,
        )

    def _error_messages(self) -> tuple[str, ...]:
        """Return this element's range, finiteness, and format errors."""
        return self._checks().all_messages()

    def validate(self) -> tuple[ValidationError, ...]:
        """Return every range, finiteness, and format error at once (no fail-fast)."""
        return tuple(
            ValidationError(self._id, self._kind, m) for m in self._error_messages()
        )

    # -- codec delegators --------------------------------------------------

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonInputNumberEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> InputNumberElement:
        """Construct an InputNumberElement from a mapping (noop handler bus; a
        ``publish`` chain raises via ``RaisingPublishSink``)."""
        decoder = JsonInputNumberDecoder(
            renderer_factory=RAISING_FACTORY,
            emit=NO_EMIT,
            element_cls=cls,
            handler_decoder=build_standalone_input_number_handler_decoder(
                cast("PublishSink", RaisingPublishSink("InputNumberElement.from_dict")),
            ),
        )
        return decoder.decode(d)

    def widget_value(self) -> float:
        """Return the value SceneManager mirrors into WidgetState after a patch."""
        return self._value

    # -- rendering support -------------------------------------------------

    def sanitized(self, value: int | float) -> int | float:
        """Return the Hub-valid value the renderer may commit — its commit guard.

        Delegates to ``NumericInputChecks.sanitized``: a raw entry is clamped, made
        integral, and re-checked against ``apply_patch``'s predicate, so a non-finite
        overflow is dropped for the validated value — the commit is never Hub-rejected.
        """
        return self._checks().sanitized(value)

    # -- introspection (Inspectable) ---------------------------------------

    def resolved_props(self) -> Mapping[str, object]:
        """Return the full resolved state, including defaulted fields."""
        return {
            "label": self._label,
            "value": self._value,
            "min": self._min,
            "max": self._max,
            "step": self._step,
            "format": self._format,
            "integer": self._integer,
            "tooltip": self._tooltip,
        }
