"""RadioElement — a set of radio buttons on the Element ABC.

An atomic-selection interactive leaf: one pick commits a discrete ``selected``
index into ``items``, exactly as a checkbox commits a boolean — no in-progress
edit to reconcile, so no ``ContinuousEditArbiter``. Keyword-only ``__new__`` with
``abc_di_defaults`` sentinels on ``renderer_factory`` / ``emit``; the Display
rebinds the real factory. The codec body lives in ``radio_codec.py``; ``to_dict``
/ ``from_dict`` stay on the class as short delegators so the runtime-checkable
``domain.element.Element`` Protocol stays satisfied.

Because ``items`` is patchable and ``selected``'s validity depends on it, the
index invariant is checked at the element boundary — ``validate()`` before
render, a whole-element re-check after ``apply_patch`` — never per setter.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, cast, final

from punt_lux.domain.element_abc import Element
from punt_lux.domain.handlers.decorators import PublishSink
from punt_lux.domain.interaction import ValueChanged
from punt_lux.domain.remote_dispatch_spec import RemoteDispatchSpec
from punt_lux.domain.validation import ValidationError
from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.patch_field import PatchField
from punt_lux.protocol.elements.radio_codec import JsonRadioDecoder, JsonRadioEncoder
from punt_lux.protocol.elements.value_change_handlers import (
    build_standalone_value_handler_decoder,
)
from punt_lux.protocol.raising_publish_sink import RaisingPublishSink

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["RadioElement"]


@final
class RadioElement(Element):
    """A set of radio buttons on the Element ABC.

    PY-TS-14 OK: ``tooltip`` stays ``str | None`` — absence is the documented
    contract for no tooltip. ``selected`` is a total ``int`` (default ``0``),
    ``items`` a total ``list[str]`` (default empty); neither is Optional.
    """

    _id: str
    _label: str
    _items: list[str]
    _selected: int
    _tooltip: str | None
    _kind: Literal["radio"]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory = RAISING_FACTORY,
        emit: Emit = NO_EMIT,
        id: str,
        label: str = "",
        items: list[str] | None = None,
        selected: int = 0,
        tooltip: str | None = None,
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._label = label
        self._items = list(items) if items is not None else []
        self._selected = selected
        self._tooltip = tooltip
        self._kind = "radio"
        return self

    # -- read-only accessors (the wire-facing surface) ----------------------

    @property
    def id(self) -> str:
        """Return the radio's stable identity within its enclosing Scene."""
        return self._id

    @property
    def kind(self) -> Literal["radio"]:
        """Return the wire discriminator — always ``"radio"``."""
        return self._kind

    @property
    def label(self) -> str:
        """Return the visible radio-group label."""
        return self._label

    @property
    def items(self) -> list[str]:
        """Return a copy of the selectable item labels."""
        return list(self._items)

    @property
    def selected(self) -> int:
        """Return the current selected index into ``items``."""
        return self._selected

    @property
    def action(self) -> Literal["changed"]:
        """Return the input action name — always ``"changed"``."""
        return "changed"

    @property
    def tooltip(self) -> str | None:
        """Return the hover-tooltip text, or None for no tooltip."""
        return self._tooltip

    # -- patch-path setters -------------------------------------------------
    # Each only coerces its field; the index invariant is re-checked once for
    # the whole element in ``apply_patch``, never per setter.

    def _set_selected(self, value: object) -> None:
        self._selected = PatchField("selected").as_int(value)

    def _set_label(self, value: object) -> None:
        self._label = PatchField("label").as_str(value)

    def _set_items(self, value: object) -> None:
        if not isinstance(value, list):
            msg = f"items must be a list, got {type(value).__name__}"
            raise TypeError(msg)
        seq = cast("list[object]", value)
        for i, item in enumerate(seq):
            if not isinstance(item, str):
                msg = f"items[{i}] must be str, got {type(item).__name__}"
                raise TypeError(msg)
        self._items = cast("list[str]", list(seq))

    def _set_tooltip(self, value: object) -> None:
        self._tooltip = PatchField("tooltip").as_optional_str(value)

    def apply_patch(self, patch: Mapping[str, object]) -> Self:
        """Apply a field patch atomically, re-checking the index at the boundary.

        A combined ``{"items": [...], "selected": n}`` must be judged on the
        final state, not per setter: the base loop rolls back on a coercion
        ``TypeError``; a whole-element re-check then rolls the whole patch back
        if the final index is out of range.
        """
        snapshot = dict(vars(self))
        super().apply_patch(patch)
        messages = self._index_error_messages()
        if messages:
            vars(self).clear()
            vars(self).update(snapshot)
            raise ValueError(messages[0])
        return self

    def _remote_dispatch_specs(self) -> tuple[RemoteDispatchSpec, ...]:
        """Return the value-changed bucket's spec under the fixed 'changed' action."""
        return (RemoteDispatchSpec(ValueChanged, self.action, "value_changed"),)

    # -- validation (DES-039) ----------------------------------------------

    def _index_error_messages(self) -> tuple[str, ...]:
        """Return the selected-index range error, if any — the shared predicate.

        A negative index is never valid. With items present the index must
        address a real item; with no items only ``0`` is meaningful (a radio
        group awaiting deferred population). Reporting — not the legacy silent
        clamp-to-0 — is what DES-039 requires.
        """
        if self._selected < 0:
            return (f"selected ({self._selected}) must be >= 0",)
        if self._items:
            if self._selected >= len(self._items):
                return (
                    f"selected ({self._selected}) must be < len(items) "
                    f"({len(self._items)})",
                )
            return ()
        if self._selected != 0:
            return (f"selected ({self._selected}) must be 0 when items is empty",)
        return ()

    def validate(self) -> tuple[ValidationError, ...]:
        """Return the selected-index error, if any (no fail-fast)."""
        return tuple(
            ValidationError(self._id, self._kind, m)
            for m in self._index_error_messages()
        )

    # -- codec delegators --------------------------------------------------

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonRadioEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> RadioElement:
        """Construct a RadioElement from a JSON-decoded mapping.

        Returns the concrete type (the class is ``@final``) so both type checkers
        agree — a ``cast`` to ``Self`` reads redundant to one and required by the
        other. Wires a noop-only handler decoder so a radio with no ``handlers``
        decodes without a publish bus; a ``publish`` chain raises via
        ``RaisingPublishSink``.
        """
        decoder = JsonRadioDecoder(
            renderer_factory=RAISING_FACTORY,
            emit=NO_EMIT,
            element_cls=cls,
            handler_decoder=build_standalone_value_handler_decoder(
                cast("PublishSink", RaisingPublishSink("RadioElement.from_dict")),
            ),
        )
        return decoder.decode(d)

    def widget_value(self) -> int:
        """Return the selected index SceneManager mirrors into WidgetState."""
        return self._selected

    # -- introspection (Inspectable) ---------------------------------------

    def resolved_props(self) -> Mapping[str, object]:
        """Return the full resolved state, including defaulted fields."""
        return {
            "label": self._label,
            "items": list(self._items),
            "selected": self._selected,
            "tooltip": self._tooltip,
        }
