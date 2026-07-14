"""CollapsingHeaderElement — an interactive collapsible section on the Element ABC.

The closest copy of ``GroupElement`` (a plain-box container: it overrides only
``_children()`` and ``validate()``) composed with the single Hub-authoritative
value pattern of ``CheckboxElement``: one ``open`` bool the user toggles, the
Hub owns, and the agent can drive. A user toggle fires ``HeaderToggled``, which
routes to the Hub; the Hub mirrors the new ``open`` and re-pushes. The
single ``open`` field is the declared initial value, the runtime value, and the
agent-driven value — it collapses the legacy ``default_open`` into one field
under Hub authority.

The codec body lives in ``collapsing_header_codec.py``; ``to_dict`` / ``from_dict``
stay here as short delegators so the runtime-checkable ``domain.element.Element``
Protocol stays satisfied (PY-OO-2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, cast

from punt_lux.domain.container_interaction import HeaderToggled
from punt_lux.domain.element_abc import Element
from punt_lux.domain.handlers.decorators import PublishSink
from punt_lux.domain.remote_dispatch_spec import RemoteDispatchSpec
from punt_lux.domain.validation import ValidationError
from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.collapsing_header_codec import (
    JsonCollapsingHeaderDecoder,
    JsonCollapsingHeaderEncoder,
)
from punt_lux.protocol.elements.container_abc_gate import ContainerAbcGate
from punt_lux.protocol.elements.container_dispatch import dispatch
from punt_lux.protocol.elements.patch_field import PatchField
from punt_lux.protocol.raising_publish_sink import RaisingPublishSink
from punt_lux.protocol.standalone_collapsing_header_handler import (
    build_standalone_collapsing_header_handler_decoder,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["CollapsingHeaderElement"]


class CollapsingHeaderElement(Element):
    """A collapsible section that owns a Hub-authoritative ``open`` flag.

    Holds only ABC children — the render template calls ``child.render()``,
    which only ABC elements provide. The decoder guarantees this by decoding a
    ``collapsing_header`` onto this class only when its entire subtree is
    migrated-ABC; any legacy descendant routes the subtree to the legacy form.

    PY-TS-14: ``tooltip`` stays ``str | None`` — absence is the documented
    contract for an optional tooltip.
    """

    _id: str
    _label: str
    _open: bool
    _children_tuple: tuple[Element, ...]
    _tooltip: str | None
    _kind: Literal["collapsing_header"]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory = RAISING_FACTORY,
        emit: Emit = NO_EMIT,
        id: str,
        label: str = "",
        open: bool = False,
        children: Iterable[Element] = (),
        tooltip: str | None = None,
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._label = label
        self._open = open
        self._children_tuple = tuple(children)
        self._tooltip = tooltip
        self._kind = "collapsing_header"
        return self

    # -- read-only accessors (the wire-facing surface) ----------------------

    @property
    def id(self) -> str:
        """Return the header's stable identity within its enclosing Scene."""
        return self._id

    @property
    def kind(self) -> Literal["collapsing_header"]:
        """Return the wire discriminator — always ``"collapsing_header"``."""
        return self._kind

    @property
    def label(self) -> str:
        """Return the header's disclosure label."""
        return self._label

    @property
    def open(self) -> bool:
        """Return the Hub-authoritative open flag — whether the body shows."""
        return self._open

    @property
    def children(self) -> tuple[Element, ...]:
        """Return the header's children (read-only view)."""
        return self._children_tuple

    @property
    def tooltip(self) -> str | None:
        """Return the hover-tooltip text, or ``None`` for no tooltip."""
        return self._tooltip

    # ``_children()``, ``child_elements()``, ``remove_child`` and factory
    # rebinding all come from the Element ABC, backed by ``_children_tuple``.
    # A plain-box header overrides no render step hook: the ABC template runs
    # ``_paint_self`` + ``_render_children`` only when the renderer's ``begin``
    # reports the header expanded.

    # -- minimal setters for the scene patch path --------------------------

    def _set_open(self, value: object) -> None:
        """Replace the Hub-authoritative open flag."""
        self._open = PatchField("open").as_bool(value)

    def _set_label(self, value: object) -> None:
        """Replace the header label."""
        self._label = PatchField("label").as_str(value)

    def _set_tooltip(self, value: object) -> None:
        """Replace the tooltip text."""
        self._tooltip = PatchField("tooltip").as_optional_str(value)

    def _remote_dispatch_specs(self) -> tuple[RemoteDispatchSpec, ...]:
        """Return the header-toggled bucket's spec under the element-id action."""
        return (RemoteDispatchSpec(HeaderToggled, self.id, "header_toggled"),)

    # -- self-validation ---------------------------------------------------

    def validate(self) -> tuple[ValidationError, ...]:
        """Return one error when the label is empty — a headerless toggle."""
        if not self._label:
            message = "collapsing_header requires a non-empty label"
            return (ValidationError(self._id, self._kind, message),)
        return ()

    # -- codec delegators ---------------------------------------------------

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonCollapsingHeaderEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        """Construct a CollapsingHeaderElement from a JSON-decoded mapping.

        Recurses children through the shared container dispatcher and rejects a
        wire dict whose subtree is not all-ABC — the invariant belongs at this
        type's own boundary, not only in the tier factory (PY-EH-1). A wire
        ``publish`` handler resolves against a ``RaisingPublishSink`` so a stray
        publish on this no-tier path fails loud rather than silently.
        """
        if not ContainerAbcGate.is_all_abc(d):
            offending = ContainerAbcGate.first_non_abc_kind(d)
            header_id = d.get("id")
            msg = (
                f"collapsing_header {header_id!r} is not all-ABC — "
                f"offending kind: {offending!r}"
            )
            raise ValueError(msg)
        decoder = JsonCollapsingHeaderDecoder(
            decode_element=dispatch.from_dict,
            element_cls=cls,
            handler_decoder=build_standalone_collapsing_header_handler_decoder(
                cast(
                    "PublishSink",
                    RaisingPublishSink("CollapsingHeaderElement.from_dict"),
                ),
            ),
        )
        return cast("Self", decoder.decode(d))

    # -- introspection (Inspectable) ---------------------------------------

    def resolved_props(self) -> Mapping[str, object]:
        """Return the full resolved state, including the authoritative view-state."""
        return {
            "label": self._label,
            "open": self._open,
            "children": [child.id for child in self._children_tuple],
            "tooltip": self._tooltip,
        }
