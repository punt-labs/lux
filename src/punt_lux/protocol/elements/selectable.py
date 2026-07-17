"""SelectableElement — a boolean toggleable list row on the Element ABC.

The atomic-toggle sibling of ``CheckboxElement``: its value is a ``bool``
committed in one click, painted as a list row via ``imgui.selectable`` instead
of ``imgui.checkbox``. Atomic, so no ``ContinuousEditArbiter``; no index into
items, so — unlike combo/radio — no cross-field invariant, hence no
``apply_patch`` override and no ``validate()`` override (a bool plus a label is
always well-formed, so the ABC's no-error default stands).

ABC subclass with keyword-only ``__new__``. The ``abc_di_defaults`` sentinels on
``renderer_factory`` / ``emit`` keep direct construction compiling; the Display
binds the real factory in its post-receive rebind. The codec body lives in
``selectable_codec.py``; ``to_dict`` / ``from_dict`` stay on the class as short
delegators so the runtime-checkable ``domain.element.Element`` Protocol stays
satisfied.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, cast, final

from punt_lux.domain.element_abc import Element
from punt_lux.domain.handlers.decorators import PublishSink
from punt_lux.domain.interaction import ValueChanged
from punt_lux.domain.remote_dispatch_spec import RemoteDispatchSpec
from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.patch_field import PatchField
from punt_lux.protocol.elements.selectable_codec import (
    JsonSelectableDecoder,
    JsonSelectableEncoder,
)
from punt_lux.protocol.elements.value_change_handlers import (
    build_standalone_value_handler_decoder,
)
from punt_lux.protocol.raising_publish_sink import RaisingPublishSink

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["SelectableElement"]


@final
class SelectableElement(Element):
    """A boolean selectable list row on the Element ABC.

    PY-TS-14 OK: ``tooltip`` stays ``str | None`` — absence is the documented
    contract for no tooltip.
    """

    _id: str
    _label: str
    _selected: bool
    _tooltip: str | None
    _kind: Literal["selectable"]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory = RAISING_FACTORY,
        emit: Emit = NO_EMIT,
        id: str,
        label: str = "",
        selected: bool = False,
        tooltip: str | None = None,
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._label = label
        self._selected = selected
        self._tooltip = tooltip
        self._kind = "selectable"
        return self

    # -- read-only accessors (the wire-facing surface) ----------------------

    @property
    def id(self) -> str:
        """Return the selectable's stable identity within its enclosing Scene."""
        return self._id

    @property
    def kind(self) -> Literal["selectable"]:
        """Return the wire discriminator — always ``"selectable"``."""
        return self._kind

    @property
    def label(self) -> str:
        """Return the visible row label."""
        return self._label

    @property
    def selected(self) -> bool:
        """Return the current on/off state."""
        return self._selected

    @property
    def action(self) -> Literal["changed"]:
        """Return the input action name — always ``"changed"``."""
        return "changed"

    @property
    def tooltip(self) -> str | None:
        """Return the hover-tooltip text, or None for no tooltip."""
        return self._tooltip

    # -- minimal setters for the scene patch path --------------------------

    def _set_selected(self, value: object) -> None:
        """Replace the selectable on/off state."""
        self._selected = PatchField("selected").as_bool(value)

    def _set_label(self, value: object) -> None:
        """Replace the row label."""
        self._label = PatchField("label").as_str(value)

    def _set_tooltip(self, value: object) -> None:
        """Replace the tooltip text."""
        self._tooltip = PatchField("tooltip").as_optional_str(value)

    def _remote_dispatch_specs(self) -> tuple[RemoteDispatchSpec, ...]:
        """Return the value-changed bucket's spec under the fixed 'changed' action."""
        return (RemoteDispatchSpec(ValueChanged, self.action, "value_changed"),)

    # -- codec delegators --------------------------------------------------

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonSelectableEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> SelectableElement:
        """Construct a SelectableElement from a JSON-decoded mapping.

        Returns the concrete type (the class is ``@final``) so both type checkers
        agree — a ``cast`` to ``Self`` reads redundant to one and required by the
        other. Wires a noop-only handler decoder so a selectable with no
        ``handlers`` decodes without a publish bus; a ``publish`` chain raises via
        ``RaisingPublishSink``.
        """
        decoder = JsonSelectableDecoder(
            renderer_factory=RAISING_FACTORY,
            emit=NO_EMIT,
            element_cls=cls,
            handler_decoder=build_standalone_value_handler_decoder(
                cast("PublishSink", RaisingPublishSink("SelectableElement.from_dict")),
            ),
        )
        return decoder.decode(d)

    def widget_value(self) -> bool:
        """Return the value SceneManager mirrors into WidgetState after a patch."""
        return self._selected

    # -- introspection (Inspectable) ---------------------------------------

    def resolved_props(self) -> Mapping[str, object]:
        """Return the full resolved state, including defaulted fields."""
        return {
            "label": self._label,
            "selected": self._selected,
            "tooltip": self._tooltip,
        }
