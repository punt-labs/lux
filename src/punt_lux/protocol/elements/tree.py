"""TreeElement — a display-only collapsible tree on the Element ABC.

ABC subclass with keyword-only ``__new__``. Sentinel defaults on
``renderer_factory`` and ``emit`` (shared through ``abc_di_defaults``) keep
direct construction compiling; the Display binds the real factory in its
post-receive rebind. A tree is a leaf: its ``nodes`` are a recursive
``TreeNode`` value family, not child elements (they carry no id, no handlers,
no independent render), so it overrides none of the render-template hooks and
its children walk is empty.

Node well-formedness is a wire-boundary concern, not a ``validate()`` one:
``TreeNode.decode_all`` rejects a non-mapping or label-less node with a
``ValueError`` at decode, before any TreeElement exists, so a constructed tree
carries only typed, well-formed nodes and has no residual invalid state to
report. Node expansion is Display-local view state — never Hub-authoritative,
never re-pushed.

The codec body lives in ``tree_codec.py`` (``JsonTreeEncoder`` /
``JsonTreeDecoder``); ``to_dict`` and ``from_dict`` remain on the class as
short delegators so the runtime-checkable ``domain.element.Element`` Protocol
stays satisfied.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Self, cast

from punt_lux.domain.element_abc import Element
from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.patch_field import PatchField
from punt_lux.protocol.elements.tree_codec import JsonTreeDecoder, JsonTreeEncoder
from punt_lux.protocol.elements.tree_node import TreeNode

if TYPE_CHECKING:
    from collections.abc import Mapping

    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["TreeElement"]


class TreeElement(Element):
    """A collapsible tree of recursive ``TreeNode`` values.

    PY-TS-14 OK: ``tooltip`` stays ``str | None`` — absence is the documented
    contract for no tooltip. ``label`` is a total ``str`` (default ``""``) and
    ``flat`` a total ``bool``; ``nodes`` is a total tuple (default empty), so
    none needs an Optional. ``flat`` renders children without indentation for
    tight horizontal space.
    """

    _id: str
    _label: str
    _nodes: tuple[TreeNode, ...]
    _flat: bool
    _tooltip: str | None
    _kind: Literal["tree"]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory = RAISING_FACTORY,
        emit: Emit = NO_EMIT,
        id: str,
        label: str = "",
        nodes: tuple[TreeNode, ...] = (),
        flat: bool = False,
        tooltip: str | None = None,
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._label = label
        self._nodes = nodes
        self._flat = flat
        self._tooltip = tooltip
        self._kind = "tree"
        return self

    @property
    def id(self) -> str:
        """Return the element's stable identity within its enclosing Scene."""
        return self._id

    @property
    def kind(self) -> Literal["tree"]:
        """Return the wire discriminator — always ``"tree"``."""
        return self._kind

    @property
    def label(self) -> str:
        """Return the tree's heading text, or ``""`` for no heading."""
        return self._label

    @property
    def nodes(self) -> tuple[TreeNode, ...]:
        """Return the top-level nodes, each a recursive ``TreeNode`` value."""
        return self._nodes

    @property
    def flat(self) -> bool:
        """Return whether children render without indentation (inline disclosure)."""
        return self._flat

    @property
    def tooltip(self) -> str | None:
        """Return the hover-tooltip text, or ``None`` for no tooltip."""
        return self._tooltip

    def _set_label(self, value: object) -> None:
        """Replace the heading text (used by ``Element.apply_patch``)."""
        self._label = PatchField("label").as_str(value)

    def _set_nodes(self, value: object) -> None:
        """Replace the node tree; a malformed node raises (``Element.apply_patch``)."""
        self._nodes = TreeNode.decode_all(value, "nodes")

    def _set_flat(self, value: object) -> None:
        """Replace the flat-layout flag (used by ``Element.apply_patch``)."""
        self._flat = PatchField("flat").as_bool(value)

    def _set_tooltip(self, value: object) -> None:
        """Replace the tooltip text (used by ``Element.apply_patch``)."""
        self._tooltip = PatchField("tooltip").as_optional_str(value)

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonTreeEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        """Construct a TreeElement from a JSON-decoded mapping."""
        decoder = JsonTreeDecoder(
            renderer_factory=RAISING_FACTORY, emit=NO_EMIT, element_cls=cls
        )
        # ``element_cls=cls`` guarantees the concrete subtype; the decoder's
        # annotation is the supertype, so narrow to ``Self`` for the Protocol.
        return cast("Self", decoder.decode(d))

    def resolved_props(self) -> Mapping[str, object]:
        """Return the full resolved state, including defaulted fields."""
        return {
            "label": self._label,
            "nodes": [node.to_dict() for node in self._nodes],
            "flat": self._flat,
            "tooltip": self._tooltip,
        }
