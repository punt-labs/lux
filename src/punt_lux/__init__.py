"""Lux — the paintbrush for Claude. Visual output surface for AI agents."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("punt-lux")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"

from punt_lux.display_client import DisplayClient
from punt_lux.paths import DisplayPaths
from punt_lux.protocol import (
    AckMessage,
    ButtonElement,
    CheckboxElement,
    ClearMessage,
    CollapsingHeaderElement,
    ColorPickerElement,
    ComboElement,
    DrawElement,
    FrameReader,
    GroupElement,
    ImageElement,
    InputTextElement,
    InteractionMessage,
    MarkdownElement,
    MenuMessage,
    PingMessage,
    PlotElement,
    PongMessage,
    ProgressElement,
    RadioElement,
    ReadyMessage,
    RegisterMenuMessage,
    SceneMessage,
    SelectableElement,
    SeparatorElement,
    SliderElement,
    SpinnerElement,
    TabBarElement,
    TableElement,
    TextElement,
    TreeElement,
    UpdateMessage,
    WindowElement,
    decode_frame,
    element_from_dict,
    encode_frame,
    encode_message,
    message_from_dict,
    message_to_dict,
    recv_message,
    send_message,
)

# Backward compatibility alias
LuxClient = DisplayClient

__all__ = [
    "AckMessage",
    "ButtonElement",
    "CheckboxElement",
    "ClearMessage",
    "CollapsingHeaderElement",
    "ColorPickerElement",
    "ComboElement",
    "DisplayClient",
    "DisplayPaths",
    "DrawElement",
    "FrameReader",
    "GroupElement",
    "ImageElement",
    "InputTextElement",
    "InteractionMessage",
    "LuxClient",
    "MarkdownElement",
    "MenuMessage",
    "PingMessage",
    "PlotElement",
    "PongMessage",
    "ProgressElement",
    "RadioElement",
    "ReadyMessage",
    "RegisterMenuMessage",
    "SceneMessage",
    "SelectableElement",
    "SeparatorElement",
    "SliderElement",
    "SpinnerElement",
    "TabBarElement",
    "TableElement",
    "TextElement",
    "TreeElement",
    "UpdateMessage",
    "WindowElement",
    "decode_frame",
    "element_from_dict",
    "encode_frame",
    "encode_message",
    "message_from_dict",
    "message_to_dict",
    "recv_message",
    "send_message",
]
