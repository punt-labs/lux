"""CheckboxElement — boolean toggle on the Element ABC.

ABC subclass with ``__new__`` keyword-only construction.  Sentinel
defaults on ``renderer_factory`` and ``emit`` (shared through
``abc_di_defaults``) keep direct-construction call sites (tests, agent
fixtures) compiling without a tier injection; the wire decode path
through ``JsonCheckboxDecoder`` always passes real values, so the runtime
DI shape on the wire path is unchanged.

The codec body lives in ``checkbox_codec.py`` (``JsonCheckboxEncoder`` /
``JsonCheckboxDecoder``); ``to_dict`` and ``from_dict`` remain on the class
as short delegators so the runtime-checkable ``domain.element.Element``
Protocol stays satisfied.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, cast

from punt_lux.domain.element_abc import Element
from punt_lux.domain.handlers.decorators import PublishSink
from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.checkbox_codec import (
    JsonCheckboxDecoder,
    JsonCheckboxEncoder,
)
from punt_lux.protocol.elements.patch_field import PatchField
from punt_lux.protocol.raising_publish_sink import RaisingPublishSink
from punt_lux.protocol.standalone_checkbox_handler import (
    build_standalone_checkbox_handler_decoder,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["CheckboxElement"]


class CheckboxElement(Element):
    """A boolean checkbox on the Element ABC.

    PY-TS-14 OK: ``tooltip`` stays ``str | None`` — absence is the
    documented contract for no tooltip.
    """

    _id: str
    _label: str
    _value: bool
    _tooltip: str | None
    _kind: Literal["checkbox"]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory = RAISING_FACTORY,
        emit: Emit = NO_EMIT,
        id: str,
        label: str = "",
        value: bool = False,
        tooltip: str | None = None,
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._label = label
        self._value = value
        self._tooltip = tooltip
        self._kind = "checkbox"
        return self

    # -- read-only accessors (the wire-facing surface) ----------------------

    @property
    def id(self) -> str:
        """Return the checkbox's stable identity within its enclosing Scene."""
        return self._id

    @property
    def kind(self) -> Literal["checkbox"]:
        """Return the wire discriminator — always ``"checkbox"``."""
        return self._kind

    @property
    def label(self) -> str:
        """Return the visible checkbox label."""
        return self._label

    @property
    def value(self) -> bool:
        """Return the current boolean state."""
        return self._value

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
        """Replace the checkbox boolean state."""
        self._value = PatchField("value").as_bool(value)

    def _set_label(self, value: object) -> None:
        """Replace the checkbox label."""
        self._label = PatchField("label").as_str(value)

    def _set_tooltip(self, value: object) -> None:
        """Replace the tooltip text."""
        self._tooltip = PatchField("tooltip").as_optional_str(value)

    # -- codec delegators --------------------------------------------------

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonCheckboxEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        """Construct a CheckboxElement from a JSON-decoded mapping.

        Wires a noop-only handler decoder so test/agent callers that
        decode a Checkbox with no ``handlers`` work without a real publish
        bus. A spec whose decorator chain invokes ``publish`` raises at
        change time through the ``RaisingPublishSink`` — the directive
        bans silent swallowing of decorator side effects.
        """
        decoder = JsonCheckboxDecoder(
            renderer_factory=RAISING_FACTORY,
            emit=NO_EMIT,
            element_cls=cls,
            handler_decoder=build_standalone_checkbox_handler_decoder(
                cast("PublishSink", RaisingPublishSink("CheckboxElement.from_dict")),
            ),
        )
        return cast("Self", decoder.decode(d))

    def widget_value(self) -> bool:
        """Return the value SceneManager mirrors into WidgetState after a patch."""
        return self._value
