"""DialogElement — composite Element with a private model and child Buttons.

A DialogElement is the canonical example of the MVC component pattern:

- The ``DialogModel`` (private to this module) holds the dialog's own
  state — visibility and confirmation — and publishes a typed verb
  vocabulary the child controllers may invoke.
- The ``DialogElement`` itself is the view: its ``visible`` property
  reflects the model, its ``_children()`` hook exposes the child
  controllers to the Composite render loop.
- The child Buttons are the controllers. The wire decoder
  (``JsonDialogDecoder``) constructs the model first, binds
  ``model.on_dismiss`` to the dialog's own ``mark_removed``, then
  decodes each child Button with a ``HandlerDecoder`` that closes over
  the model — so a child Button's ``call_model`` factory resolves the
  wire verb against the model's vocabulary at decode time.

The model's ``_dismiss`` reaches the Element ABC's ``mark_removed``
through the bound callback; the Element ABC's observer cascade is what
notifies the dialog's parent composite that the dialog is gone.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, ClassVar, Literal, Self, cast

from punt_lux.domain.element_abc import Element
from punt_lux.protocol.elements.dialog_codec import (
    JsonDialogDecoder,
    JsonDialogEncoder,
)
from punt_lux.protocol.renderers.raising import RaisingRendererFactory

if TYPE_CHECKING:
    from punt_lux.protocol.renderer import Emit, RendererFactory

__all__ = ["DialogElement", "DialogModel"]


_RAISING_FACTORY: RendererFactory = RaisingRendererFactory()


def _no_emit(_msg: object) -> None:
    """Sentinel emit channel — Hub-tier no-op (PY-DP-9 Null Object)."""


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
        renderer_factory: RendererFactory = _RAISING_FACTORY,
        emit: Emit = _no_emit,
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
        """Hook override — Composite render walks these in order."""
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

    def _set_title(self, value: object) -> None:
        """Replace the dialog title."""
        self._title = self._str_or_raise(value, "title")

    def _set_tooltip(self, value: object) -> None:
        """Replace the tooltip text."""
        self._tooltip = self._opt_str_or_raise(value, "tooltip")

    # -- codec delegators --------------------------------------------------

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-compatible wire representation."""
        return JsonDialogEncoder().encode(self)

    @classmethod
    def from_dict(cls, d: Mapping[str, object]) -> Self:
        """Construct a DialogElement from a JSON-decoded mapping."""
        decoder = JsonDialogDecoder(
            renderer_factory=_RAISING_FACTORY,
            emit=_no_emit,
            element_cls=cls,
        )
        return cast("Self", decoder.decode(d))
