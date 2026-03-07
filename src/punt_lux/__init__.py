"""Lux — the paintbrush for Claude. Visual output surface for AI agents."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("punt-lux")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"

from punt_lux.client import LuxClient
from punt_lux.paths import default_socket_path, ensure_display
from punt_lux.protocol import (
    AckMessage,
    ButtonElement,
    CheckboxElement,
    ClearMessage,
    ColorPickerElement,
    ComboElement,
    FrameReader,
    ImageElement,
    InputTextElement,
    InteractionMessage,
    PingMessage,
    PongMessage,
    RadioElement,
    ReadyMessage,
    SceneMessage,
    SeparatorElement,
    SliderElement,
    TextElement,
    UpdateMessage,
    WindowMessage,
    decode_frame,
    element_from_dict,
    encode_frame,
    encode_message,
    message_from_dict,
    message_to_dict,
    recv_message,
    send_message,
)

__all__ = [
    "AckMessage",
    "ButtonElement",
    "CheckboxElement",
    "ClearMessage",
    "ColorPickerElement",
    "ComboElement",
    "FrameReader",
    "ImageElement",
    "InputTextElement",
    "InteractionMessage",
    "LuxClient",
    "PingMessage",
    "PongMessage",
    "RadioElement",
    "ReadyMessage",
    "SceneMessage",
    "SeparatorElement",
    "SliderElement",
    "TextElement",
    "UpdateMessage",
    "WindowMessage",
    "decode_frame",
    "default_socket_path",
    "element_from_dict",
    "encode_frame",
    "encode_message",
    "ensure_display",
    "message_from_dict",
    "message_to_dict",
    "recv_message",
    "send_message",
]
