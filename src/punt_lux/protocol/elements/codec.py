"""Element codec registry — dispatch table mapping element kinds to codec pairs."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Self, cast

if TYPE_CHECKING:
    from punt_lux.protocol.elements import Element

__all__ = [
    "ElementCodec",
    "Register",
]


_Serializer = Callable[..., dict[str, Any]]
_Deserializer = Callable[[dict[str, Any]], Any]

_CodecEntry = tuple[type, _Serializer, _Deserializer]

# The callback that family modules accept in ``register_codecs(register)``.
# Exported so family modules can type their ``register`` parameter without
# redeclaring the alias five times.
Register = Callable[[str, type, _Serializer, _Deserializer], None]


class ElementCodec:
    """Dispatch table mapping element ``kind`` strings to codec pairs.

    Instance-based so tests can construct isolated registries without
    polluting the module-level default.  The production registry is a
    module-level instance populated at import time from each family
    module's ``register_codecs`` callback.

    A missing, empty, non-string, or unknown ``kind`` raises
    ``ValueError`` on decode — elements have no equivalent of
    ``UnknownMessage``.  Unknown classes raise ``TypeError`` on encode.
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
        kind: str,
        cls: type,
        to_fn: _Serializer,
        from_fn: _Deserializer,
    ) -> None:
        """Register an element kind's codec pair."""
        if kind in self._codecs:
            msg = f"Duplicate element registration: {kind!r}"
            raise ValueError(msg)
        if cls in self._serializers:
            msg = f"Duplicate class registration: {cls.__name__}"
            raise ValueError(msg)
        self._codecs[kind] = (cls, to_fn, from_fn)
        self._serializers[cls] = to_fn

    def to_dict(self, elem: Element) -> dict[str, Any]:
        """Serialize an Element to a JSON-compatible dict."""
        serializer = self._serializers.get(type(elem))
        if serializer is not None:
            return serializer(elem)
        err = f"Unknown element type: {type(elem)}"
        raise TypeError(err)

    def from_dict(self, d: dict[str, Any]) -> Element:
        """Deserialize a dict to the appropriate Element.

        A missing, empty, or non-string ``kind`` raises ``ValueError``;
        an unrecognized ``kind`` raises ``ValueError`` — elements have
        no forward-compatible unknown fallback (cf. ``UnknownMessage``).
        Mirrors ``MessageRegistry.from_dict``'s contract for the wire
        ``type`` field.
        """
        kind = d.get("kind")
        if not isinstance(kind, str) or not kind:
            err = "Element missing or invalid 'kind' field"
            raise ValueError(err)
        codec = self._codecs.get(kind)
        if codec is None:
            err = f"Unknown element kind: {kind!r}"
            raise ValueError(err)
        _, _, from_fn = codec
        return cast("Element", from_fn(d))

    @property
    def registered_kinds(self) -> frozenset[str]:
        """Return the set of registered ``kind`` strings."""
        return frozenset(self._codecs)
