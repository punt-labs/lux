"""ColorPickerElement — an RGB(A) color picker on the Element ABC.

ABC subclass with keyword-only ``__new__``. The ``abc_di_defaults`` sentinels on
``renderer_factory`` / ``emit`` keep direct construction compiling; the Display
binds the real factory in its post-receive rebind.

The wire value is a hex string (``#RRGGBB`` / ``#RRGGBBAA``); the RGBA float
tuple the ImGui widget works in is a Display-local render detail (never a field
here). ``alpha`` and ``picker`` stay two orthogonal ``bool``s — a channel-count
axis and a widget-style axis — not a merged four-way ``Literal``.

The codec body lives in ``color_picker_codec.py``; ``to_dict`` / ``from_dict``
stay on the class as short delegators so the runtime-checkable
``domain.element.Element`` Protocol stays satisfied. The built-in
``_UpdateValueHandler`` (installed by the decoder) mirrors the authoritative hex
on each commit. There is no ``apply_patch`` override — the only per-field
invariant is ``value``'s hex well-formedness, re-checked by ``validate()`` before
render, so the base setter loop suffices.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Literal, Self, cast, final

from punt_lux.domain.element_abc import Element
from punt_lux.domain.handlers.decorators import PublishSink
from punt_lux.domain.interaction import ValueChanged
from punt_lux.domain.remote_dispatch_spec import RemoteDispatchSpec
from punt_lux.domain.validation import ValidationError
from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.color_picker_codec import (
    JsonColorPickerDecoder,
    JsonColorPickerEncoder,
)
from punt_lux.protocol.elements.patch_field import PatchField
from punt_lux.protocol.raising_publish_sink import RaisingPublishSink
from punt_lux.protocol.standalone_color_picker_handler import (
    build_standalone_color_picker_handler_decoder,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["ColorPickerElement"]

# A well-formed hex color: ``#`` then exactly 6 or 8 hexadecimal digits.
_HEX_COLOR = re.compile(r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{8})")


@final
class ColorPickerElement(Element):
    """An RGB(A) color picker on the Element ABC.

    PY-TS-14 OK: ``tooltip`` stays ``str | None`` — absence is the documented
    contract for no tooltip. ``value`` is a total ``str`` (a hex color). ``alpha``
    (RGBA channel count) and ``picker`` (full-picker vs inline-edit widget) are
    genuine two-state flags, not deferred types.
    """

    _id: str
    _label: str
    _value: str
    _alpha: bool
    _picker: bool
    _tooltip: str | None
    _kind: Literal["color_picker"]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory = RAISING_FACTORY,
        emit: Emit = NO_EMIT,
        id: str,
        label: str = "",
        value: str = "#FFFFFF",
        alpha: bool = False,
        picker: bool = False,
        tooltip: str | None = None,
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._label = label
        self._value = value
        self._alpha = alpha
        self._picker = picker
        self._tooltip = tooltip
        self._kind = "color_picker"
        return self

    # -- read-only accessors (the wire-facing surface) ----------------------

    @property
    def id(self) -> str:
        """Return the picker's stable identity within its enclosing Scene."""
        return self._id

    @property
    def kind(self) -> Literal["color_picker"]:
        """Return the wire discriminator — always ``"color_picker"``."""
        return self._kind

    @property
    def label(self) -> str:
        """Return the visible picker label."""
        return self._label

    @property
    def value(self) -> str:
        """Return the current color as a hex string (``#RRGGBB`` / ``#RRGGBBAA``)."""
        return self._value

    @property
    def alpha(self) -> bool:
        """Return whether the picker renders the RGBA (four-channel) variant."""
        return self._alpha

    @property
    def picker(self) -> bool:
        """Return whether the picker uses the full-picker (not inline-edit) variant."""
        return self._picker

    @property
    def action(self) -> Literal["changed"]:
        """Return the input action name — always ``"changed"``."""
        return "changed"

    @property
    def tooltip(self) -> str | None:
        """Return the hover-tooltip text, or None for no tooltip."""
        return self._tooltip

    # -- minimal setters for the scene patch path --------------------------
    # No ``apply_patch`` override: there is no cross-field invariant, and a hex
    # patch is a single field re-checked by ``validate`` before render.

    def _set_value(self, value: object) -> None:
        """Replace the hex color value."""
        self._value = PatchField("value").as_str(value)

    def _set_label(self, value: object) -> None:
        """Replace the picker label."""
        self._label = PatchField("label").as_str(value)

    def _set_alpha(self, value: object) -> None:
        """Replace the RGBA-variant flag."""
        self._alpha = PatchField("alpha").as_bool(value)

    def _set_picker(self, value: object) -> None:
        """Replace the full-picker-variant flag."""
        self._picker = PatchField("picker").as_bool(value)

    def _set_tooltip(self, value: object) -> None:
        """Replace the tooltip text."""
        self._tooltip = PatchField("tooltip").as_optional_str(value)

    def _remote_dispatch_specs(self) -> tuple[RemoteDispatchSpec, ...]:
        """Return the value-changed bucket's spec under the fixed 'changed' action."""
        return (RemoteDispatchSpec(ValueChanged, self.action, "value_changed"),)

    # -- validation (DES-039) ----------------------------------------------

    def validate(self) -> tuple[ValidationError, ...]:
        """Return the hex-well-formedness error, if any.

        The value must be ``#`` followed by exactly 6 or 8 hex digits. This is
        the reconciliation-soundness precondition, not a mere paint nicety: a
        well-formed hex parses to finite ``[0, 1]`` floats, so the RGBA tuple the
        reconciliation carries never holds a ``NaN`` and tuple equality stays
        reflexive. It subsumes the finiteness check ``slider`` needs a
        ``math.isfinite`` loop for — the hex encoding cannot express a non-finite
        channel — so there is no such loop here.

        Length is *not* checked against ``alpha`` (a deliberate leniency, not an
        omission): a 6-digit value under ``alpha`` pads to opaque and an 8-digit
        value under RGB drops its alpha in the encoder, both accepted. That
        leniency is what lets the base ``apply_patch`` stand without a boundary
        re-check override.
        """
        if _HEX_COLOR.fullmatch(self._value) is None:
            msg = f"value must be #RRGGBB or #RRGGBBAA hex, got {self._value!r}"
            return (ValidationError(self._id, self._kind, msg),)
        return ()

    # -- codec delegators --------------------------------------------------

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonColorPickerEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> ColorPickerElement:
        """Construct a ColorPickerElement from a JSON-decoded mapping.

        Wires a noop-only handler decoder so a picker with no ``handlers`` decodes
        without a publish bus; a ``publish`` chain raises via ``RaisingPublishSink``.
        """
        decoder = JsonColorPickerDecoder(
            renderer_factory=RAISING_FACTORY,
            emit=NO_EMIT,
            element_cls=cls,
            handler_decoder=build_standalone_color_picker_handler_decoder(
                cast("PublishSink", RaisingPublishSink("ColorPickerElement.from_dict")),
            ),
        )
        return decoder.decode(d)

    def widget_value(self) -> str:
        """Return the hex value SceneManager mirrors into WidgetState after a patch."""
        return self._value

    # -- introspection (Inspectable) ---------------------------------------

    def resolved_props(self) -> Mapping[str, object]:
        """Return the full resolved state, including defaulted fields."""
        return {
            "value": self._value,
            "alpha": self._alpha,
            "picker": self._picker,
            "tooltip": self._tooltip,
        }
