"""GroupElement — the first container on the Element ABC path.

A display-only layout container: it owns an ordered tuple of ABC child
elements and arranges them in a ``rows`` or ``columns`` stack. It is
``Dialog`` minus the interactive machinery, plus a ``layout``
discriminator — no model, no dismiss verb, no observer cascade of its
own. The render template drives its ImGui adapter's ``begin``/``end``
(the layout choice lives in the renderer); ``paint`` is a no-op because a
container's only body is its children.

Only stack layouts (``rows`` / ``columns``) live on this class. The
``paged`` layout stays entirely on :class:`LegacyGroupElement`, which
owns the paged wire fields (``pages`` / ``page_source``) and the paged
renderer; the all-ABC gate routes a ``paged`` group there (see
:mod:`group_codec`), so an ABC ``GroupElement`` never carries them.

The codec body lives in ``group_codec.py`` (``JsonGroupEncoder`` /
``JsonGroupDecoder``); ``to_dict`` / ``from_dict`` remain here as thin
delegators so the runtime-checkable ``domain.element.Element`` Protocol
stays satisfied, mirroring the ``Dialog`` split precedent (PY-OO-2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, cast

from punt_lux.domain.element_abc import Element
from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.container_dispatch import dispatch
from punt_lux.protocol.elements.group_codec import JsonGroupDecoder, JsonGroupEncoder

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["GroupElement"]

type Layout = Literal["rows", "columns"]


class GroupElement(Element):
    """A layout container that arranges its ABC children in a stack.

    An ABC ``GroupElement`` holds only ABC children — the render template
    calls ``child.render()``, which only ABC elements provide. The wire
    decoder guarantees this by decoding a ``group`` onto this class only
    when its entire subtree is migrated-ABC and its layout is a stack
    (rows / columns); any legacy descendant routes the whole subtree to
    the legacy container instead.

    PY-TS-14: ``tooltip`` stays ``str | None`` — absence is the documented
    contract for an optional tooltip.
    """

    _id: str
    _layout: Layout
    _children_tuple: tuple[Element, ...]
    _tooltip: str | None
    _kind: Literal["group"]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory = RAISING_FACTORY,
        emit: Emit = NO_EMIT,
        id: str,
        layout: Layout = "rows",
        children: Iterable[Element] = (),
        tooltip: str | None = None,
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._layout = layout
        self._children_tuple = tuple(children)
        self._tooltip = tooltip
        self._kind = "group"
        return self

    # -- read-only accessors (the wire-facing surface) ----------------------

    @property
    def id(self) -> str:
        """Return the group's stable identity within its enclosing Scene."""
        return self._id

    @property
    def kind(self) -> Literal["group"]:
        """Return the wire discriminator — always ``"group"``."""
        return self._kind

    @property
    def layout(self) -> Layout:
        """Return how the group arranges its children."""
        return self._layout

    @property
    def children(self) -> tuple[Element, ...]:
        """Return the group's always-visible children (read-only view)."""
        return self._children_tuple

    @property
    def tooltip(self) -> str | None:
        """Return the hover-tooltip text, or ``None`` for no tooltip."""
        return self._tooltip

    # The render-visible children, remove_child (physical removal), and the
    # validation-walk bridge all come from the Element ABC, which stores the
    # tuple this group populates in ``__new__``. A rows/columns group needs no
    # override — the layout surface is opened by the ImGui adapter's begin/end.

    # -- codec delegators ---------------------------------------------------

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonGroupEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        """Construct a GroupElement from a JSON-decoded mapping.

        Recurses children through the shared container dispatcher (the
        agent-side ``element_from_dict``), so an all-ABC subtree decodes
        to ABC children exactly as the tier factory would. Rejects a wire
        dict whose subtree is not all-ABC — the invariant belongs at this
        type's own boundary, not only in the tier factory (PY-EH-1).
        """
        if not JsonGroupDecoder.is_all_abc(d):
            offending = JsonGroupDecoder.first_non_abc_kind(d)
            group_id = d.get("id")
            msg = (
                f"group {group_id!r} is not an all-ABC stack group — "
                f"offending kind or layout: {offending!r}"
            )
            raise ValueError(msg)
        decoder = JsonGroupDecoder(
            decode_element=dispatch.from_dict,
            element_cls=cls,
        )
        return cast("Self", decoder.decode(d))

    # -- introspection (Inspectable) ---------------------------------------

    def resolved_props(self) -> Mapping[str, object]:
        """Return the full resolved state, including defaulted fields."""
        return {
            "layout": self._layout,
            "children": [child.id for child in self._children_tuple],
            "tooltip": self._tooltip,
        }
