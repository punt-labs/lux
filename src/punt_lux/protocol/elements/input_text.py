"""InputTextElement — a single-line text input on the Element ABC.

ABC subclass with keyword-only ``__new__``. The ``abc_di_defaults`` sentinels
on ``renderer_factory`` / ``emit`` keep direct construction compiling; the
Display binds the real factory in its post-receive rebind.

The codec body lives in ``input_text_codec.py``; ``to_dict`` / ``from_dict``
stay on the class as short delegators so the runtime-checkable
``domain.element.Element`` Protocol stays satisfied. The Element ABC /
``EventHandlerHost`` mixin owns the value-changed registry and dispatch; the
built-in ``_UpdateTextHandler`` (installed by the decoder) mirrors the
authoritative text on each edit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, cast, final

from punt_lux.domain.element_abc import Element
from punt_lux.domain.handlers.decorators import PublishSink
from punt_lux.domain.interaction import ValueChanged
from punt_lux.domain.remote_dispatch_spec import RemoteDispatchSpec
from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.input_text_codec import (
    JsonInputTextDecoder,
    JsonInputTextEncoder,
)
from punt_lux.protocol.elements.patch_field import PatchField
from punt_lux.protocol.raising_publish_sink import RaisingPublishSink
from punt_lux.protocol.standalone_input_text_handler import (
    build_standalone_input_text_handler_decoder,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["InputTextElement"]


@final
class InputTextElement(Element):
    """A single-line text input on the Element ABC.

    PY-TS-14 OK: ``tooltip`` stays ``str | None`` — absence is the documented
    contract for no tooltip. ``value`` and ``hint`` are total ``str`` (default
    ``""``, the discriminated "empty text" / "no placeholder" states).
    """

    _id: str
    _label: str
    _value: str
    _hint: str
    _tooltip: str | None
    _kind: Literal["input_text"]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory = RAISING_FACTORY,
        emit: Emit = NO_EMIT,
        id: str,
        label: str = "",
        value: str = "",
        hint: str = "",
        tooltip: str | None = None,
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._label = label
        self._value = value
        self._hint = hint
        self._tooltip = tooltip
        self._kind = "input_text"
        return self

    # -- read-only accessors (the wire-facing surface) ----------------------

    @property
    def id(self) -> str:
        """Return the input's stable identity within its enclosing Scene."""
        return self._id

    @property
    def kind(self) -> Literal["input_text"]:
        """Return the wire discriminator — always ``"input_text"``."""
        return self._kind

    @property
    def label(self) -> str:
        """Return the visible input label."""
        return self._label

    @property
    def value(self) -> str:
        """Return the current text."""
        return self._value

    @property
    def hint(self) -> str:
        """Return the placeholder shown while the field is empty, or ``""``."""
        return self._hint

    @property
    def action(self) -> Literal["changed"]:
        """Return the input action name — always ``"changed"``."""
        return "changed"

    @property
    def tooltip(self) -> str | None:
        """Return the hover-tooltip text, or None for no tooltip."""
        return self._tooltip

    # -- minimal setters for the scene patch path --------------------------

    def _set_value(self, value: object) -> None:
        """Replace the input text."""
        self._value = PatchField("value").as_str(value)

    def _set_label(self, value: object) -> None:
        """Replace the input label."""
        self._label = PatchField("label").as_str(value)

    def _set_hint(self, value: object) -> None:
        """Replace the placeholder hint."""
        self._hint = PatchField("hint").as_str(value)

    def _set_tooltip(self, value: object) -> None:
        """Replace the tooltip text."""
        self._tooltip = PatchField("tooltip").as_optional_str(value)

    def _remote_dispatch_specs(self) -> tuple[RemoteDispatchSpec, ...]:
        """Return the value-changed bucket's spec under the fixed 'changed' action."""
        return (RemoteDispatchSpec(ValueChanged, self.action, "value_changed"),)

    # -- codec delegators --------------------------------------------------

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonInputTextEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> InputTextElement:
        """Construct an InputTextElement from a JSON-decoded mapping.

        Returns the concrete type (the class is ``@final``). Wires a noop-only
        handler decoder so an input with no ``handlers`` decodes without a
        publish bus; a ``publish`` decorator chain raises via ``RaisingPublishSink``.
        """
        decoder = JsonInputTextDecoder(
            renderer_factory=RAISING_FACTORY,
            emit=NO_EMIT,
            element_cls=cls,
            handler_decoder=build_standalone_input_text_handler_decoder(
                cast("PublishSink", RaisingPublishSink("InputTextElement.from_dict")),
            ),
        )
        return decoder.decode(d)

    # -- introspection (Inspectable) ---------------------------------------

    def resolved_props(self) -> Mapping[str, object]:
        """Return the full resolved state, including defaulted fields."""
        return {
            "label": self._label,
            "value": self._value,
            "hint": self._hint,
            "tooltip": self._tooltip,
        }
