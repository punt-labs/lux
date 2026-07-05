"""GroupElement — the first container on the Element ABC path.

A display-only layout container: it owns an ordered tuple of ABC child
elements and arranges them in a ``rows`` or ``columns`` stack. It is
``Dialog`` minus the interactive machinery, plus a ``layout``
discriminator — no model, no dismiss verb, no observer cascade of its
own. The render template drives its ImGui adapter's ``begin``/``end``
(the layout choice lives in the renderer); ``paint`` is a no-op because a
container's only body is its children.

The ``paged`` layout and its ``pages`` / ``page_source`` fields exist on
the class and codec for wire compatibility, but paged rendering is a
separate follow-up: an all-ABC ``group`` only decodes onto this class for
``rows`` / ``columns`` (see :mod:`group_codec`).

The codec body lives in ``group_codec.py`` (``JsonGroupEncoder`` /
``JsonGroupDecoder``); ``to_dict`` / ``from_dict`` remain here as thin
delegators so the runtime-checkable ``domain.element.Element`` Protocol
stays satisfied, mirroring the ``Dialog`` split precedent (PY-OO-2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, cast

from punt_lux.domain.element_abc import Element
from punt_lux.domain.validation import ValidationError
from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.container_dispatch import dispatch
from punt_lux.protocol.elements.group_codec import JsonGroupDecoder, JsonGroupEncoder

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["GroupElement"]

type Layout = Literal["rows", "columns", "paged"]


class GroupElement(Element):
    """A layout container that arranges its ABC children in a stack.

    An ABC ``GroupElement`` holds only ABC children — the render template
    calls ``child.render()``, which only ABC elements provide. The wire
    decoder guarantees this by decoding a ``group`` onto this class only
    when its entire subtree is migrated-ABC and its layout is a stack
    (rows / columns); any legacy descendant routes the whole subtree to
    the legacy container instead.

    PY-TS-14: ``tooltip`` stays ``str | None`` — absence is the documented
    contract for an optional tooltip. ``page_source`` is ``str`` with
    ``""`` as the discriminated "no page-source" state (the encoder omits
    it when empty, so the wire shape is unchanged), the same move
    ``TextElement.color`` made.
    """

    _id: str
    _layout: Layout
    _children_tuple: tuple[Element, ...]
    _pages: tuple[tuple[Element, ...], ...]
    _page_source: str
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
        pages: Iterable[Iterable[Element]] = (),
        page_source: str = "",
        tooltip: str | None = None,
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._layout = layout
        self._children_tuple = tuple(children)
        self._pages = tuple(tuple(page) for page in pages)
        self._page_source = page_source
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
    def pages(self) -> tuple[tuple[Element, ...], ...]:
        """Return the paged content panels (empty for a rows/columns group)."""
        return self._pages

    @property
    def page_source(self) -> str:
        """Return the id of the combo driving the page index, ``""`` if none."""
        return self._page_source

    @property
    def tooltip(self) -> str | None:
        """Return the hover-tooltip text, or ``None`` for no tooltip."""
        return self._tooltip

    # -- render + validation hooks ------------------------------------------

    def _children(self) -> tuple[Element, ...]:
        """Return the render-visible children for the default recursion.

        For a rows/columns group this is every child; the layout surface
        is opened by the ImGui adapter's ``begin``/``end`` around them.
        """
        return self._children_tuple

    def child_elements(self) -> tuple[Element, ...]:
        """Return children AND every paged element for the validation walk.

        Distinct from :meth:`_children` (the render-visible set): an
        element installed on a non-active page is not currently painted
        but is still part of the scene and must be validated.
        """
        paged = tuple(elem for page in self._pages for elem in page)
        return (*self._children_tuple, *paged)

    def validate(self) -> tuple[ValidationError, ...]:
        """Return this group's own structural errors.

        A group with ``layout='paged'`` and a non-empty ``page_source``
        must name a child id that exists; a dangling ``page_source``
        yields a paged group whose combo drives nothing — a silent no-op
        the agent should see. Child validity is collected by the
        hierarchy walk, not here.
        """
        if self._layout != "paged" or not self._page_source:
            return ()
        if any(child.id == self._page_source for child in self._children_tuple):
            return ()
        message = f"page_source {self._page_source!r} names no child of this group"
        return (
            ValidationError(
                element_id=self._id,
                element_kind="group",
                message=message,
            ),
        )

    # -- codec delegators ---------------------------------------------------

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonGroupEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        """Construct a GroupElement from a JSON-decoded mapping.

        Recurses children through the shared container dispatcher (the
        agent-side ``element_from_dict``), so an all-ABC subtree decodes
        to ABC children exactly as the tier factory would.
        """
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
            "pages": [[elem.id for elem in page] for page in self._pages],
            "page_source": self._page_source,
            "tooltip": self._tooltip,
        }
