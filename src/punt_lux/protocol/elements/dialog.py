"""DialogElement — composite Element with a private model and child Buttons.

The canonical MVC component: the private ``DialogModel`` holds state
(visibility, confirmation) and a typed verb vocabulary; the
``DialogElement`` is the view (its ``visible`` reflects the model, its
``_children()`` exposes the child controllers); the child Buttons are the
controllers. The decoder binds ``model.on_dismiss`` to the dialog's
``mark_removed``, so ``_dismiss`` flows through the Element ABC's observer
cascade to notify the parent composite.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, ClassVar, Literal, Self, cast

from punt_lux.domain.element_abc import Element
from punt_lux.domain.handlers.decorators import PublishSink
from punt_lux.protocol.elements.abc_di_defaults import NO_EMIT, RAISING_FACTORY
from punt_lux.protocol.elements.dialog_codec import (
    JsonDialogDecoder,
    JsonDialogEncoder,
)
from punt_lux.protocol.elements.patch_field import PatchField
from punt_lux.protocol.raising_publish_sink import RaisingPublishSink

if TYPE_CHECKING:
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["DialogElement"]


class DialogModel:
    """The Dialog's private state and verb vocabulary.

    Owned by ``DialogElement`` — no code outside the dialog component
    constructs this or invokes its methods except through the typed
    verb dispatcher ``invoke``. ``_dismiss`` reaches the Element ABC's
    ``mark_removed`` via the ``on_dismiss`` callback installed at
    construction time.
    """

    _ACTIONS: ClassVar[Mapping[str, Callable[[DialogModel], None]]] = {
        "confirm": lambda self: self.confirm(),
        "cancel": lambda self: self.cancel(),
        "close": lambda self: self.close(),
        "dismiss": lambda self: self.cancel(),
    }

    _visible: bool
    _confirmed: bool
    _on_dismiss: Callable[[], None]

    def __new__(cls, *, on_dismiss: Callable[[], None]) -> Self:
        self = super().__new__(cls)
        self._visible = True
        self._confirmed = False
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
        """Return whether the dialog should currently be drawn."""
        return self._visible

    @property
    def confirmed(self) -> bool:
        """Return whether the user confirmed the dialog before dismissal."""
        return self._confirmed

    def known_verbs(self) -> frozenset[str]:
        """Return the verb names ``invoke`` accepts (VerbVocabulary Protocol)."""
        return frozenset(self._ACTIONS)

    def invoke(self, action: str) -> None:
        """Dispatch ``action`` against the dialog's verb vocabulary."""
        action_fn = self._ACTIONS.get(action)
        if action_fn is None:
            msg = (
                f"unknown dialog action: {action!r} "
                f"(expected one of {sorted(self._ACTIONS)})"
            )
            raise ValueError(msg)
        action_fn(self)

    def confirm(self) -> None:
        """Record confirmation and dismiss the dialog."""
        self._confirmed = True
        self._dismiss()

    def cancel(self) -> None:
        """Dismiss the dialog without recording confirmation."""
        self._dismiss()

    def close(self) -> None:
        """Dismiss the dialog (semantic alias for an unspecified close)."""
        self._dismiss()

    def _dismiss(self) -> None:
        """Drop visibility and notify the owning Element through the callback."""
        self._visible = False
        self._on_dismiss()


class DialogElement(Element):
    """A composite Element whose state is owned by a private DialogModel.

    The dialog renders only while the model reports ``visible``. The
    Element ABC's ``_removed`` flag and observer cascade carry removal
    upward; the model invokes ``on_dismiss`` (bound at construction time
    to ``self.mark_removed``) to flip ``_removed``.
    """

    _id: str
    _title: str
    _model: DialogModel
    _children_tuple: tuple[Element, ...]
    _tooltip: str | None
    _kind: Literal["dialog"]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory = RAISING_FACTORY,
        emit: Emit = NO_EMIT,
        id: str,
        title: str = "",
        tooltip: str | None = None,
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._title = title
        self._tooltip = tooltip
        self._children_tuple = ()
        self._kind = "dialog"
        # ``on_dismiss`` binds to this Element's mark_removed so the
        # single removal mechanism (agent RemoveElement, model dismiss,
        # connection disconnect) all converge.
        self._model = DialogModel(on_dismiss=self.mark_removed)
        return self

    # -- read-only accessors -----------------------------------------------

    @property
    def id(self) -> str:
        """Return the dialog's stable identity within its enclosing Scene."""
        return self._id

    @property
    def kind(self) -> Literal["dialog"]:
        """Return the wire discriminator — always ``"dialog"``."""
        return self._kind

    @property
    def title(self) -> str:
        """Return the dialog title text."""
        return self._title

    @property
    def visible(self) -> bool:
        """Return the model's visibility — the view is a function of state."""
        return self._model.visible

    @property
    def confirmed(self) -> bool:
        """Return whether the user confirmed before dismissing the dialog."""
        return self._model.confirmed

    @property
    def tooltip(self) -> str | None:
        """Return the hover-tooltip text, or None for no tooltip."""
        return self._tooltip

    @property
    def model(self) -> DialogModel:
        """Return the model — public read so decoders can resolve verbs.

        The decoder needs the model reference to wire child Button
        handlers via ``BoundVerb.resolve_against``. The model is otherwise
        internal to the component; agents and renderers never touch it.
        """
        return self._model

    @property
    def children(self) -> tuple[Element, ...]:
        """Return the dialog's child controllers (read-only view)."""
        return self._children_tuple

    def _children(self) -> tuple[Element, ...]:
        """Hook override — Composite render walks these in order.

        The dialog overrides no render step hook: the ABC defaults already
        drive its renderer's ``begin``/``paint``/``end``, and the dialog's
        ImGui renderer encodes the modal open/close + Escape-dismiss seam.
        """
        return self._children_tuple

    # -- decoder seam ------------------------------------------------------

    def install_children(self, children: tuple[Element, ...]) -> None:
        """Install the dialog's child controllers after the model is bound.

        Used by ``JsonDialogDecoder`` once the model exists; the children
        decode against the model the dialog has already constructed.
        Calling twice replaces the previous children — the decoder owns
        the lifecycle, not the agent.
        """
        self._children_tuple = children

    # -- minimal setters for the scene patch path --------------------------

    def _set_title(self, value: object) -> None:
        """Replace the dialog title."""
        self._title = PatchField("title").as_str(value)

    def _set_tooltip(self, value: object) -> None:
        """Replace the tooltip text."""
        self._tooltip = PatchField("tooltip").as_optional_str(value)

    # -- codec delegators --------------------------------------------------

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonDialogEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        """Construct a DialogElement from a JSON-decoded mapping.

        Wires a ``RaisingPublishSink`` so callers that don't supply a
        real Hub sink (legacy ``element_from_dict`` agent path, ad-hoc
        decode in tests) still get a well-typed dialog. A child Button
        whose decorator chain invokes ``publish`` raises ``RuntimeError``
        at click time — the directive bans silent swallowing of the
        publish path. Tests that exercise publish must construct
        ``JsonDialogDecoder`` directly with a real sink.
        """
        decoder = JsonDialogDecoder(
            renderer_factory=RAISING_FACTORY,
            emit=NO_EMIT,
            element_cls=cls,
            publish_sink=cast(
                "PublishSink", RaisingPublishSink("DialogElement.from_dict")
            ),
        )
        return cast("Self", decoder.decode(d))

    # -- introspection (Inspectable) ---------------------------------------

    def resolved_props(self) -> Mapping[str, object]:
        """Return the full resolved state, including model-derived fields."""
        return {
            "title": self._title,
            "visible": self._model.visible,
            "confirmed": self._model.confirmed,
            "tooltip": self._tooltip,
        }
