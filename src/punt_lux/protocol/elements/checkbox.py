"""CheckboxElement — boolean toggle on the Element ABC.

ABC subclass with ``__new__`` keyword-only construction.  Sentinel defaults
on ``renderer_factory`` and ``emit`` keep direct-construction call sites
(tests, agent fixtures) compiling without a tier injection; the wire
decode path through ``JsonCheckboxDecoder`` always passes real values, so
the runtime DI shape on the wire path is unchanged.

The codec body lives in ``checkbox_codec.py`` (``JsonCheckboxEncoder`` /
``JsonCheckboxDecoder``); ``to_dict`` and ``from_dict`` remain on the class
as short delegators so the runtime-checkable ``domain.element.Element``
Protocol stays satisfied.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, cast

from punt_lux.domain.element_abc import Element
from punt_lux.domain.handlers.decorators import PublishSink
from punt_lux.protocol.elements.checkbox_codec import (
    JsonCheckboxDecoder,
    JsonCheckboxEncoder,
)
from punt_lux.protocol.raising_publish_sink import RaisingPublishSink
from punt_lux.protocol.renderers.raising import RaisingRendererFactory
from punt_lux.protocol.standalone_checkbox_handler import (
    build_standalone_checkbox_handler_decoder,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["CheckboxElement"]


_RAISING_FACTORY: RendererFactory = RaisingRendererFactory()


def _no_emit(_msg: object) -> None:
    """Sentinel emit channel — Hub-tier no-op (PY-DP-9 Null Object)."""


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
        renderer_factory: RendererFactory = _RAISING_FACTORY,
        emit: Emit = _no_emit,
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

    @staticmethod
    def _str_or_raise(value: object, field: str) -> str:
        """Return ``value`` as ``str`` or raise ``TypeError`` (PY-EH-1)."""
        if not isinstance(value, str):
            msg = f"{field} must be str, got {type(value).__name__}"
            raise TypeError(msg)
        return value

    @staticmethod
    def _opt_str_or_raise(value: object, field: str) -> str | None:
        """Return ``value`` as ``str | None`` or raise ``TypeError`` (PY-EH-1)."""
        if value is None or isinstance(value, str):
            return value
        msg = f"{field} must be str or None, got {type(value).__name__}"
        raise TypeError(msg)

    @staticmethod
    def _bool_or_raise(value: object, field: str) -> bool:
        """Return ``value`` as ``bool`` or raise ``TypeError`` (PY-EH-1)."""
        if not isinstance(value, bool):
            msg = f"{field} must be bool, got {type(value).__name__}"
            raise TypeError(msg)
        return value

    def _set_value(self, value: object) -> None:
        """Replace the checkbox boolean state."""
        self._value = self._bool_or_raise(value, "value")

    def _set_label(self, value: object) -> None:
        """Replace the checkbox label."""
        self._label = self._str_or_raise(value, "label")

    def _set_tooltip(self, value: object) -> None:
        """Replace the tooltip text."""
        self._tooltip = self._opt_str_or_raise(value, "tooltip")

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
            renderer_factory=_RAISING_FACTORY,
            emit=_no_emit,
            element_cls=cls,
            handler_decoder=build_standalone_checkbox_handler_decoder(
                cast("PublishSink", RaisingPublishSink("CheckboxElement.from_dict")),
            ),
        )
        return cast("Self", decoder.decode(d))

    def widget_value(self) -> bool:
        """Return the value SceneManager mirrors into WidgetState after a patch."""
        return self._value
