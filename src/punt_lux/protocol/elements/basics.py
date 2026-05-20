"""Static display primitives — text, image, separator, progress, spinner."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

__all__ = [
    "ImageElement",
    "MarkdownElement",
    "ProgressElement",
    "SeparatorElement",
    "SpinnerElement",
    "TextElement",
    "_strip_none",
    "register_codecs",
]


@dataclass(frozen=True, slots=True)
class ImageElement:
    """An image to display."""

    id: str
    kind: Literal["image"] = "image"
    path: str | None = None
    data: str | None = None  # base64-encoded
    format: str | None = None  # "png", "jpeg", "svg"
    alt: str | None = None
    width: int | None = None
    height: int | None = None
    tooltip: str | None = None

    def __post_init__(self) -> None:
        if self.path is None and self.data is None:
            msg = "ImageElement requires either 'path' or 'data'"
            raise ValueError(msg)


@dataclass(frozen=True, slots=True)
class TextElement:
    """A text block."""

    id: str
    content: str
    kind: Literal["text"] = "text"
    style: str | None = None  # "body", "heading", "caption", "code"
    tooltip: str | None = None
    color: str | None = None  # hex color e.g. "#FF3333"


@dataclass(frozen=True, slots=True)
class SeparatorElement:
    """A visual divider."""

    kind: Literal["separator"] = "separator"
    id: str | None = None
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class ProgressElement:
    """A progress bar."""

    id: str
    kind: Literal["progress"] = "progress"
    fraction: float = 0.0
    label: str = ""
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class SpinnerElement:
    """An animated loading spinner."""

    id: str
    kind: Literal["spinner"] = "spinner"
    label: str = ""
    radius: float = 16.0
    color: str = "#3399FF"
    tooltip: str | None = None


@dataclass(frozen=True, slots=True)
class MarkdownElement:
    """A block of rendered markdown text."""

    id: str
    content: str
    kind: Literal["markdown"] = "markdown"
    tooltip: str | None = None


def _strip_none(d: dict[str, Any]) -> dict[str, Any]:
    """Remove keys whose value is None."""
    return {k: v for k, v in d.items() if v is not None}


def _image_to_dict(elem: ImageElement) -> dict[str, Any]:
    return _strip_none(
        {
            "kind": elem.kind,
            "id": elem.id,
            "path": elem.path,
            "data": elem.data,
            "format": elem.format,
            "alt": elem.alt,
            "width": elem.width,
            "height": elem.height,
        }
    )


def _text_to_dict(elem: TextElement) -> dict[str, Any]:
    return _strip_none(
        {
            "kind": elem.kind,
            "id": elem.id,
            "content": elem.content,
            "style": elem.style,
            "color": elem.color,
        }
    )


def _separator_to_dict(elem: SeparatorElement) -> dict[str, Any]:
    d: dict[str, Any] = {"kind": elem.kind}
    if elem.id is not None:
        d["id"] = elem.id
    return d


def _progress_to_dict(elem: ProgressElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "fraction": elem.fraction,
    }
    if elem.label:
        d["label"] = elem.label
    return d


def _spinner_to_dict(elem: SpinnerElement) -> dict[str, Any]:
    d: dict[str, Any] = {
        "kind": elem.kind,
        "id": elem.id,
        "radius": elem.radius,
        "color": elem.color,
    }
    if elem.label:
        d["label"] = elem.label
    return d


def _markdown_to_dict(elem: MarkdownElement) -> dict[str, Any]:
    return {
        "kind": elem.kind,
        "id": elem.id,
        "content": elem.content,
    }


def _image_from_dict(d: dict[str, Any]) -> ImageElement:
    return ImageElement(
        id=d["id"],
        path=d.get("path"),
        data=d.get("data"),
        format=d.get("format"),
        alt=d.get("alt"),
        width=d.get("width"),
        height=d.get("height"),
    )


def _text_from_dict(d: dict[str, Any]) -> TextElement:
    return TextElement(
        id=d["id"],
        content=d.get("content", ""),
        style=d.get("style"),
        color=d.get("color"),
    )


def _separator_from_dict(d: dict[str, Any]) -> SeparatorElement:
    return SeparatorElement(id=d.get("id"))


def _progress_from_dict(d: dict[str, Any]) -> ProgressElement:
    return ProgressElement(
        id=d["id"],
        fraction=d.get("fraction", 0.0),
        label=d.get("label", ""),
    )


def _spinner_from_dict(d: dict[str, Any]) -> SpinnerElement:
    return SpinnerElement(
        id=d["id"],
        label=d.get("label", ""),
        radius=d.get("radius", 16.0),
        color=d.get("color", "#3399FF"),
    )


def _markdown_from_dict(d: dict[str, Any]) -> MarkdownElement:
    return MarkdownElement(
        id=d["id"],
        content=d.get("content", ""),
    )


_Register = Callable[
    [str, type, Callable[..., dict[str, Any]], Callable[[dict[str, Any]], Any]],
    None,
]


def register_codecs(register: _Register) -> None:
    """Register this module's element codecs into an ElementCodec."""
    register("image", ImageElement, _image_to_dict, _image_from_dict)
    register("text", TextElement, _text_to_dict, _text_from_dict)
    register("separator", SeparatorElement, _separator_to_dict, _separator_from_dict)
    register("progress", ProgressElement, _progress_to_dict, _progress_from_dict)
    register("spinner", SpinnerElement, _spinner_to_dict, _spinner_from_dict)
    register("markdown", MarkdownElement, _markdown_to_dict, _markdown_from_dict)
