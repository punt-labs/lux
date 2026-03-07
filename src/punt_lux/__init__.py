"""Lux — the paintbrush for Claude. Visual output surface for AI agents."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("punt-lux")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"

from punt_lux.paths import default_socket_path, ensure_display
from punt_lux.protocol import (
    AckMessage,
    ButtonElement,
    ClearMessage,
    FrameReader,
    ImageElement,
    InteractionMessage,
    PingMessage,
    PongMessage,
    ReadyMessage,
    SceneMessage,
    SeparatorElement,
    TextElement,
    UpdateMessage,
    WindowMessage,
    decode_frame,
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
    "ClearMessage",
    "FrameReader",
    "ImageElement",
    "InteractionMessage",
    "PingMessage",
    "PongMessage",
    "ReadyMessage",
    "SceneMessage",
    "SeparatorElement",
    "TextElement",
    "UpdateMessage",
    "WindowMessage",
    "decode_frame",
    "default_socket_path",
    "encode_frame",
    "encode_message",
    "ensure_display",
    "message_from_dict",
    "message_to_dict",
    "recv_message",
    "send_message",
]
