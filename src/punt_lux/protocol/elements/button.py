"""ButtonElement — io-model button on the Element ABC.

ABC subclass with ``__new__`` keyword-only construction. Sentinel defaults
on ``renderer_factory`` and ``emit`` keep direct-construction call sites
(tests, agent fixtures) compiling without a tier injection; the wire
decode path through ``JsonButtonDecoder`` always passes real values, so
the runtime DI shape on the wire path is unchanged.

The codec body lives in ``button_codec.py`` (``JsonButtonEncoder`` /
``JsonButtonDecoder``); ``to_dict`` and ``from_dict`` remain on the class
as short delegators so the runtime-checkable ``domain.element.Element``
Protocol stays satisfied.

Click handlers installed via ``add_handler(ButtonClicked, handler)`` are
populated by the wire ``HandlerDecoder`` against ``ButtonHandlers`` from
the per-Element handler catalog. The Element ABC owns the registry and
dispatch loop; this class adds only the wire-facing fields the renderer
reads.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, cast

from punt_lux.domain.element_abc import Element
from punt_lux.domain.handlers.decorators import PublishSink
from punt_lux.protocol.elements.button_codec import (
    JsonButtonDecoder,
    JsonButtonEncoder,
)
from punt_lux.protocol.raising_publish_sink import RaisingPublishSink
from punt_lux.protocol.renderers.raising import RaisingRendererFactory
from punt_lux.protocol.standalone_button_handler import (
    build_standalone_button_handler_decoder,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["ButtonElement"]


_RAISING_FACTORY: RendererFactory = RaisingRendererFactory()


def _no_emit(_msg: object) -> None:
    """Sentinel emit channel — Hub-tier no-op (PY-DP-9 Null Object)."""


class ButtonElement(Element):
    """A clickable button on the Element ABC.

    PY-TS-14: ``action`` and ``arrow`` stay ``str | None`` — ``action``
    None means "renderer falls back to ``id``" (the documented contract
    the renderer enforces), and ``arrow`` None means "not an arrow
    button". ``tooltip`` None is the absent-tooltip contract.
    """

    _id: str
    _label: str
    _action: str | None
    _disabled: bool
    _small: bool
    _arrow: str | None
    _tooltip: str | None
    _kind: Literal["button"]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory = _RAISING_FACTORY,
        emit: Emit = _no_emit,
        id: str,
        label: str = "",
        action: str | None = None,
        disabled: bool = False,
        small: bool = False,
        arrow: str | None = None,
        tooltip: str | None = None,
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._label = label
        self._action = action
        self._disabled = disabled
        self._small = small
        self._arrow = arrow
        self._tooltip = tooltip
        self._kind = "button"
        return self

    # -- read-only accessors (the wire-facing surface) ----------------------

    @property
    def id(self) -> str:
        """Return the button's stable identity within its enclosing Scene."""
        return self._id

    @property
    def kind(self) -> Literal["button"]:
        """Return the wire discriminator — always ``"button"``."""
        return self._kind

    @property
    def label(self) -> str:
        """Return the visible button label."""
        return self._label

    @property
    def action(self) -> str | None:
        """Return the action name, or None for the id-as-action default."""
        return self._action

    @property
    def disabled(self) -> bool:
        """Return whether the button is rendered as disabled."""
        return self._disabled

    @property
    def small(self) -> bool:
        """Return whether the button uses the ImGui SmallButton variant."""
        return self._small

    @property
    def arrow(self) -> str | None:
        """Return the arrow direction, or None for a standard button."""
        return self._arrow

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

    def _set_label(self, value: object) -> None:
        """Replace the button label."""
        self._label = self._str_or_raise(value, "label")

    def _set_action(self, value: object) -> None:
        """Replace the action name."""
        self._action = self._opt_str_or_raise(value, "action")

    def _set_disabled(self, value: object) -> None:
        """Replace the disabled flag."""
        self._disabled = self._bool_or_raise(value, "disabled")

    def _set_small(self, value: object) -> None:
        """Replace the small-variant flag."""
        self._small = self._bool_or_raise(value, "small")

    def _set_arrow(self, value: object) -> None:
        """Replace the arrow direction."""
        self._arrow = self._opt_str_or_raise(value, "arrow")

    def _set_tooltip(self, value: object) -> None:
        """Replace the tooltip text."""
        self._tooltip = self._opt_str_or_raise(value, "tooltip")

    # -- codec delegators --------------------------------------------------

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonButtonEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        """Construct a ButtonElement from a JSON-decoded mapping.

        Wires a noop-only handler decoder so test/agent callers that
        decode a Button with no ``handlers`` work without a real publish
        bus. A spec carrying a ``handlers[].wrap`` entry that invokes
        the publish decorator raises at click time through the
        ``RaisingPublishSink`` — the directive bans silent swallowing
        of decorator side effects.
        """
        decoder = JsonButtonDecoder(
            renderer_factory=_RAISING_FACTORY,
            emit=_no_emit,
            element_cls=cls,
            handler_decoder=build_standalone_button_handler_decoder(
                cast("PublishSink", RaisingPublishSink("ButtonElement.from_dict")),
            ),
        )
        return cast("Self", decoder.decode(d))
