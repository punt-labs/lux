"""Message codec registry — dispatch table mapping type strings to codec pairs."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Self, cast

from punt_lux.protocol.messages.lifecycle import UnknownMessage

if TYPE_CHECKING:
    from punt_lux.protocol.messages import Message

__all__ = [
    "MessageRegistry",
]


_Serializer = Callable[..., dict[str, Any]]
_Deserializer = Callable[[dict[str, Any]], Any]

_CodecEntry = tuple[type, _Serializer, _Deserializer]


class MessageRegistry:
    """Dispatch table mapping type strings to codec pairs.

    Instance-based so tests can create isolated registries without
    polluting the module-level default.  The production registry is
    a module-level instance populated at import time.

    Unregistered ``type`` strings fall through to ``UnknownMessage`` so
    forward-compatible clients never disconnect on unknown payloads.
    """

    _codecs: dict[str, _CodecEntry]
    _serializers: dict[type, _Serializer]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._codecs = {}
        self._serializers = {}
        return self

    def register(
        self,
        type_str: str,
        cls: type,
        to_fn: _Serializer,
        from_fn: _Deserializer,
    ) -> None:
        """Register a message type's codec pair."""
        if type_str in self._codecs:
            msg = f"Duplicate message registration: {type_str!r}"
            raise ValueError(msg)
        if cls in self._serializers:
            msg = f"Duplicate class registration: {cls.__name__}"
            raise ValueError(msg)
        self._codecs[type_str] = (cls, to_fn, from_fn)
        self._serializers[cls] = to_fn

    def to_dict(self, msg: Message) -> dict[str, Any]:
        """Serialize a Message to a JSON-compatible dict."""
        serializer = self._serializers.get(type(msg))
        if serializer is not None:
            return serializer(msg)
        err = f"Unknown message type: {type(msg)}"
        raise TypeError(err)

    def from_dict(self, d: dict[str, Any]) -> Message:
        """Deserialize a JSON dict to the appropriate Message."""
        msg_type = d.get("type", "")
        if not isinstance(msg_type, str) or not msg_type:
            err = "Message missing or invalid 'type' field"
            raise ValueError(err)
        codec = self._codecs.get(msg_type)
        if codec is not None:
            _, _, from_fn = codec
            return cast("Message", from_fn(d))
        return cast("Message", UnknownMessage(raw_type=msg_type, data=d))

    @property
    def registered_types(self) -> frozenset[str]:
        """Return the set of registered type strings."""
        return frozenset(self._codecs)

    @property
    def serializers(self) -> dict[type, _Serializer]:
        """Return the serializer mapping (read-only copy)."""
        return dict(self._serializers)
