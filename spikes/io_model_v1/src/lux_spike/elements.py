"""Concrete Element kinds for the spike: Label, Button, Panel, Dialog.

- Label: leaf, no behavior.
- Button: leaf, on_click behavior + optional bound callback that runs after emit.
- Panel: composite, holds children.
- Dialog: composite with a close() behavior method that emits RemoveElement.
  Its child Buttons are wired at construction time to call dialog.close on click.

The Dialog illustrates classic OO: a class with both data (its children)
and behavior (close, dismiss-self) whose API is referenced by the handlers
its children carry. The HUB's interaction dispatcher does not know that
dialogs close on click — it just invokes button.on_click(), and the bound
behavior the dialog wired into the button does the right thing.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Self

from lux_spike.element import Element
from lux_spike.updates import ButtonClicked, RemoveElement

if TYPE_CHECKING:
    from lux_spike.protocols import Emit, RendererFactory


class LabelElement(Element):
    """Leaf, no behavior. Background thread mutates content via SetProperty."""

    _id: str
    _content: str

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        id: str,
        content: str,
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._content = content
        return self

    @property
    def id(self) -> str:
        return self._id

    @property
    def content(self) -> str:
        return self._content

    def _set_content(self, value: str) -> None:
        """Used by Display.apply(SetProperty(...)) to mutate the local mirror."""
        self._content = value


class ButtonElement(Element):
    """Leaf, with on_click behavior.

    Two things happen when the OWNER tier (HUB) invokes on_click():
      1. Emit a ButtonClicked Event so observers can react.
      2. If a callback was bound at construction time, invoke it. The
         callback is typically another Element's behavior method (e.g.
         dialog.close). The button does not know what the callback does
         — it just calls it — that's how OO composition works.
    """

    _id: str
    _label: str
    _on_click_callback: Callable[[], None] | None

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        id: str,
        label: str,
        on_click_callback: Callable[[], None] | None = None,
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._label = label
        self._on_click_callback = on_click_callback
        return self

    @property
    def id(self) -> str:
        return self._id

    @property
    def label(self) -> str:
        return self._label

    def on_click(self) -> None:
        """Behavior method — emit the click Event, then invoke the bound
        callback if one was wired in at construction. A button without a
        callback is a pure-notification button (R3); a button inside a
        Dialog has `dialog.close` as its callback (R4)."""
        self._emit(ButtonClicked(elem_id=self._id))
        if self._on_click_callback is not None:
            self._on_click_callback()


class PanelElement(Element):
    """Composite. Owns its children tuple."""

    _id: str
    _children_tuple: tuple[Element, ...]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        id: str,
        children: tuple[Element, ...],
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._children_tuple = children
        return self

    @property
    def id(self) -> str:
        return self._id

    def _children(self) -> tuple[Element, ...]:
        return self._children_tuple

    def _replace_children(self, new_children: tuple[Element, ...]) -> None:
        """Used when Display.apply(AddElement) appends a child."""
        self._children_tuple = new_children


class DialogElement(Element):
    """Composite with a `close()` behavior method.

    On the OWNER tier (HUB), `close()` emits `RemoveElement(self._id)` —
    a domain Update that the tier's emit handler routes to its state
    owner (HUB accepts + ships to DISP). The Dialog knows how to
    dismiss itself; clients reference that behavior.

    On non-owner tiers (DISP), `close()` exists but its emit is a no-op
    (DISP's emit callback discards messages, by io-model.md design).
    The Dialog renders as a Panel-like composite; the close() behavior
    is invoked only on the HUB instance."""

    _id: str
    _children_tuple: tuple[Element, ...]

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        id: str,
        children: tuple[Element, ...] = (),
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._children_tuple = children
        return self

    @property
    def id(self) -> str:
        return self._id

    def _children(self) -> tuple[Element, ...]:
        return self._children_tuple

    def _set_children(self, children: tuple[Element, ...]) -> None:
        """Used by the decoder to install children after construction —
        needed because the Dialog reference must exist before its child
        Buttons can bind `dialog.close` as their on_click callback."""
        self._children_tuple = children

    def close(self) -> None:
        """Dismiss this Dialog from its tier's state owner. The behavior
        emits a RemoveElement Update targeting self; the owner tier's
        emit handler accepts the Update and (on HUB) ships it to DISP."""
        self._emit(RemoveElement(elem_id=self._id))
