"""ModalElement — a composite Element whose visibility is owned by a private model.

The interactive-composite shape, copied from ``DialogElement``: the private
``ModalModel`` holds visibility and the single dismiss verb; the ``ModalElement``
is the view (its ``open`` flag reflects the model, its ``_children()`` exposes the
popup body). Unlike a dialog its children are arbitrary ABC elements, not
model-bound controllers, so it recurses them through the shared container
dispatcher like ``GroupElement`` rather than decoding them against the model.

A user close routes to the Hub as a ``ModalClosed`` interaction (declared via
``_remote_dispatch_specs``), where the built-in dismiss handler drives
``model.close`` -> ``mark_removed``; the Element ABC's observer cascade then
removes the modal from both tiers — the same D21 removal path a dialog dismiss
uses. The codec body lives in ``modal_codec.py``; ``to_dict`` / ``from_dict``
stay here as short delegators so the structural ``domain.element.Element``
Protocol stays satisfied (PY-OO-2).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar, Literal, Self, cast

from punt_lux.domain.container_interaction import ModalClosed
from punt_lux.domain.element_abc import Element
from punt_lux.domain.handlers.publish_sink import PublishSink
from punt_lux.domain.remote_dispatch_spec import RemoteDispatchSpec
from punt_lux.domain.validation import ValidationError
from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.container_dispatch import dispatch
from punt_lux.protocol.elements.modal_codec import JsonModalDecoder, JsonModalEncoder
from punt_lux.protocol.elements.patch_field import PatchField
from punt_lux.protocol.elements.window import WindowElement
from punt_lux.protocol.raising_publish_sink import RaisingPublishSink
from punt_lux.protocol.standalone_modal_handler import (
    build_standalone_modal_handler_decoder,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["ModalElement", "ModalModel"]


class ModalModel:
    """The Modal's private visibility state and single dismiss verb.

    Owned by ``ModalElement`` — nothing outside the modal component constructs
    this or calls its methods. ``close`` reaches the Element ABC's
    ``mark_removed`` via the ``on_dismiss`` callback installed at construction,
    so the one removal mechanism (agent ``RemoveElement``, user dismiss,
    connection disconnect) stays shared.
    """

    _visible: bool
    _on_dismiss: Callable[[], None]

    def __new__(cls, *, visible: bool, on_dismiss: Callable[[], None]) -> Self:
        self = super().__new__(cls)
        self._visible = visible
        self._on_dismiss = on_dismiss
        return self

    def __reduce__(self) -> tuple[object, ...]:
        """Support native serialization for Hub-to-Display transport."""
        return (object.__new__, (type(self),), self.__dict__.copy())

    def __setstate__(self, state: dict[str, object]) -> None:
        """Restore instance state after native deserialization."""
        for key, value in state.items():
            object.__setattr__(self, key, value)

    @property
    def visible(self) -> bool:
        """Return whether the modal should currently be drawn."""
        return self._visible

    def close(self) -> None:
        """Drop visibility and notify the owning Element through the callback."""
        self._visible = False
        self._on_dismiss()


class ModalElement(Element):
    """A composite Element whose visibility is owned by a private ModalModel.

    The modal renders only while the model reports ``visible``. Holds only ABC
    children — the render template calls ``child.render()``, which only ABC
    elements provide; the decoder guarantees this by decoding a ``modal`` onto
    this class only when its entire subtree is migrated-ABC.

    PY-TS-14: ``tooltip`` stays ``str | None`` — absence is the documented
    contract for an optional tooltip.
    """

    _id: str
    _title: str
    _model: ModalModel
    _children_tuple: tuple[Element, ...]
    _tooltip: str | None
    _kind: Literal["modal"]

    # A window always floats top-level (see WindowElement), so nesting one in a
    # modal makes it escape while the modal blocks its escaped child — incoherent,
    # so forbidden at both boundaries anywhere in the subtree.
    _NO_WINDOW_IN_MODAL: ClassVar[str] = (
        "a window cannot nest inside a modal — a window always floats top-level; "
        "use group or collapsing_header for panels"
    )

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory = RAISING_FACTORY,
        emit: Emit = NO_EMIT,
        id: str,
        title: str = "",
        open: bool = True,
        tooltip: str | None = None,
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._title = title
        self._tooltip = tooltip
        self._children_tuple = ()
        self._kind = "modal"
        # ``open`` seeds the initial visibility; the user's only visibility
        # transition is the dismiss, which removes the modal via ``mark_removed``.
        self._model = ModalModel(visible=open, on_dismiss=self.mark_removed)
        return self

    # -- read-only accessors -----------------------------------------------

    @property
    def id(self) -> str:
        """Return the modal's stable identity within its enclosing Scene."""
        return self._id

    @property
    def kind(self) -> Literal["modal"]:
        """Return the wire discriminator — always ``"modal"``."""
        return self._kind

    @property
    def title(self) -> str:
        """Return the modal title text."""
        return self._title

    @property
    def open(self) -> bool:
        """Return the modal's open flag — the view is a function of model state.

        Named for the wire field an agent sets and reads; it reflects the private
        model's visibility, which the dismiss flips to closed before removal.
        """
        return self._model.visible

    @property
    def tooltip(self) -> str | None:
        """Return the hover-tooltip text, or ``None`` for no tooltip."""
        return self._tooltip

    @property
    def model(self) -> ModalModel:
        """Return the model — the display adapter reads visibility from it.

        The model is otherwise internal to the component; agents and renderers
        never construct it or call its methods except through the dismiss path.
        """
        return self._model

    @property
    def children(self) -> tuple[Element, ...]:
        """Return the modal's body children (read-only view)."""
        return self._children_tuple

    # ``_children()``, ``child_elements``, ``remove_child`` and factory
    # rebinding come from the Element ABC, backed by ``_children_tuple``.

    # -- decoder seam ------------------------------------------------------

    def install_children(self, children: tuple[Element, ...]) -> None:
        """Install the modal's body children after the model is bound.

        Used by ``JsonModalDecoder`` once the element exists. Calling twice
        replaces the previous children — the decoder owns the lifecycle.
        """
        self._children_tuple = children

    # -- minimal setters for the scene patch path --------------------------

    def _set_title(self, value: object) -> None:
        """Replace the modal title."""
        self._title = PatchField("title").as_str(value)

    def _set_tooltip(self, value: object) -> None:
        """Replace the tooltip text."""
        self._tooltip = PatchField("tooltip").as_optional_str(value)

    def _remote_dispatch_specs(self) -> tuple[RemoteDispatchSpec, ...]:
        """Return the modal-closed bucket's spec under the element-id action."""
        return (RemoteDispatchSpec(ModalClosed, self.id, "modal_closed"),)

    # -- self-validation ---------------------------------------------------

    def validate(self) -> tuple[ValidationError, ...]:
        """Reject a ``window`` anywhere in the subtree (see ``_NO_WINDOW_IN_MODAL``)."""
        if self._first_window_descendant() is None:
            return ()
        return (ValidationError(self._id, self._kind, self._NO_WINDOW_IN_MODAL),)

    def _first_window_descendant(self) -> Element | None:
        """Return the first ``window`` anywhere in the subtree, or ``None``."""
        stack = list(self.child_elements())
        while stack:
            elem = stack.pop()
            if isinstance(elem, WindowElement):
                return elem
            stack.extend(elem.child_elements())
        return None

    # -- codec delegators --------------------------------------------------

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonModalEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        """Construct a ModalElement from a JSON-decoded mapping.

        Recurses children through the shared container dispatcher, which rejects
        an unknown child kind (PY-EH-1). A wire ``publish`` handler resolves
        against a ``RaisingPublishSink`` so a stray publish on this no-tier path
        fails loud rather than silently.
        """
        decoder = JsonModalDecoder(
            decode_element=dispatch.from_dict,
            element_cls=cls,
            handler_decoder=build_standalone_modal_handler_decoder(
                cast("PublishSink", RaisingPublishSink("ModalElement.from_dict")),
            ),
        )
        modal = cast("Self", decoder.decode(d))
        # The invariant rides with the decode boundary too (PY-EH-1): a modal
        # whose subtree nests a window is rejected here, not only at validate().
        if modal._first_window_descendant() is not None:
            raise ValueError(f"modal {modal.id!r}: {cls._NO_WINDOW_IN_MODAL}")
        return modal

    # -- introspection (Inspectable) ---------------------------------------

    def resolved_props(self) -> Mapping[str, object]:
        """Return the full resolved state, including the model-derived open flag."""
        return {
            "title": self._title,
            "open": self._model.visible,
            "children": [child.id for child in self._children_tuple],
            "tooltip": self._tooltip,
        }
