"""TextRendererFactory — Display-tier surface that prints scenes to a TextOutput.

Per-kind classes per io-model.md §"Per-kind renderers".
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Self

from lux_spike.elements import ButtonElement, DialogElement, LabelElement, PanelElement

if TYPE_CHECKING:
    from lux_spike.element import Element


class TextOutput:
    """Surface-shared state — collects lines for one tick. The factory
    holds this; per-kind renderers receive it via constructor."""

    _lines: list[str]
    _indent: int

    def __new__(cls) -> Self:
        self = object.__new__(cls)
        self._lines = []
        self._indent = 0
        return self

    def line(self, text: str) -> None:
        self._lines.append("  " * self._indent + text)

    def indent(self) -> None:
        self._indent += 1

    def dedent(self) -> None:
        self._indent = max(0, self._indent - 1)

    def take(self) -> list[str]:
        out = self._lines
        self._lines = []
        self._indent = 0
        return out


class TextLabelRenderer:
    _elem: LabelElement
    _out: TextOutput

    def __new__(cls, elem: LabelElement, out: TextOutput) -> Self:
        self = object.__new__(cls)
        self._elem = elem
        self._out = out
        return self

    def render(self) -> None:
        self._out.line(f"Label[{self._elem.id}]: {self._elem.content}")

    def begin(self) -> None:
        pass

    def end(self) -> None:
        pass


class TextButtonRenderer:
    _elem: ButtonElement
    _out: TextOutput

    def __new__(cls, elem: ButtonElement, out: TextOutput) -> Self:
        self = object.__new__(cls)
        self._elem = elem
        self._out = out
        return self

    def render(self) -> None:
        self._out.line(f"Button[{self._elem.id}]: [{self._elem.label}]")

    def begin(self) -> None:
        pass

    def end(self) -> None:
        pass


class TextPanelRenderer:
    _elem: PanelElement
    _out: TextOutput

    def __new__(cls, elem: PanelElement, out: TextOutput) -> Self:
        self = object.__new__(cls)
        self._elem = elem
        self._out = out
        return self

    def render(self) -> None:
        pass

    def begin(self) -> None:
        self._out.line(f"Panel[{self._elem.id}] {{")
        self._out.indent()

    def end(self) -> None:
        self._out.dedent()
        self._out.line("}")


class TextDialogRenderer:
    _elem: DialogElement
    _out: TextOutput

    def __new__(cls, elem: DialogElement, out: TextOutput) -> Self:
        self = object.__new__(cls)
        self._elem = elem
        self._out = out
        return self

    def render(self) -> None:
        pass

    def begin(self) -> None:
        self._out.line(f"Dialog[{self._elem.id}] {{")
        self._out.indent()

    def end(self) -> None:
        self._out.dedent()
        self._out.line("}")


class TextRendererFactory:
    _out: TextOutput

    def __new__(cls, out: TextOutput) -> Self:
        self = object.__new__(cls)
        self._out = out
        return self

    def __call__(
        self, elem: Element
    ) -> TextLabelRenderer | TextButtonRenderer | TextPanelRenderer | TextDialogRenderer:
        match elem:
            case LabelElement():
                return TextLabelRenderer(elem, self._out)
            case ButtonElement():
                return TextButtonRenderer(elem, self._out)
            case PanelElement():
                return TextPanelRenderer(elem, self._out)
            case DialogElement():
                return TextDialogRenderer(elem, self._out)
            case _:
                raise ValueError(f"text surface has no renderer for {type(elem).__name__}")
