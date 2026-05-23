"""Concrete Element kinds for the spike: Label, Button, Panel.

One leaf with no behavior (Label), one leaf with behavior (Button),
one composite (Panel). Smallest vocabulary that exercises the
Composite pattern + behavior method + the template-method render.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from lux_spike.element import Element
from lux_spike.updates import ButtonClicked

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
    """Leaf, with on_click behavior. Display detects ImGui-equivalent
    click → ships InteractionMessage → Hub looks up button → calls on_click."""

    _id: str
    _label: str

    def __new__(
        cls,
        *,
        renderer_factory: RendererFactory,
        emit: Emit,
        id: str,
        label: str,
    ) -> Self:
        self = super().__new__(cls, renderer_factory=renderer_factory, emit=emit)
        self._id = id
        self._label = label
        return self

    @property
    def id(self) -> str:
        return self._id

    @property
    def label(self) -> str:
        return self._label

    def on_click(self) -> None:
        """Behavior method — emits ButtonClicked Event."""
        self._emit(ButtonClicked(elem_id=self._id))


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
