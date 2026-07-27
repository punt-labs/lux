"""Transport a scene's elements as base64 pickles across the Hub→Display wire.

Every element in a ``SceneMessage`` crosses as a ``{"_pickled": <base64>}``
entry rather than a JSON element dict: pickling preserves the Hub-side handlers
the Display re-wraps for remote dispatch. This codec owns that leg in both
directions — it pickles each element on the way out and reconstructs it on the
way in, rejecting a version-skewed or non-element pickle by name so a bad frame
is refused at the boundary instead of crashing the display.
"""

from __future__ import annotations

import base64
import pickle
from typing import TYPE_CHECKING, Any, Self, cast

from punt_lux.domain.element_abc import Element as AbcElement

if TYPE_CHECKING:
    from collections.abc import Sequence

    from punt_lux.protocol.elements import Element

__all__ = ["PickledElementCodec"]


class PickledElementCodec:
    """Encode/decode a scene's elements as their ``_pickled`` wire entries."""

    __slots__ = ()

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def encode_all(self, elements: Sequence[Element]) -> list[dict[str, Any]]:
        """Pickle each element into its ``{"_pickled": <base64>}`` wire entry."""
        return [
            {"_pickled": base64.b64encode(pickle.dumps(e)).decode("ascii")}
            for e in elements
        ]

    def decode_all(self, raw: object) -> list[Element]:
        """Decode the wire elements — omission/non-list is malformed, not empty."""
        if not isinstance(raw, list):
            raise ValueError(f"scene elements must be a present list, got {raw!r}")
        return [self._decode_entry(e) for e in cast("list[object]", raw)]

    def _decode_entry(self, e: object) -> Element:
        """Reconstruct one element; a non-dict or non-``_pickled`` entry is refused."""
        if not isinstance(e, dict):
            raise ValueError(f"scene element must be a dict, got {e!r}")
        entry = cast("dict[str, Any]", e)
        pickled = entry.get("_pickled")
        if pickled is None:
            raise ValueError(
                f"scene element must carry a '_pickled' entry, got {entry!r}"
            )
        return self._unpickle(pickled)

    @staticmethod
    def _unpickle(pickled: object) -> Element:
        """Reconstruct an element from its base64 pickle, or reject it by name.

        Pickling is the only Hub-to-Display transport, so an unhandled raise here
        crosses the socket boundary and kills the display (``_on_frame`` has no
        error boundary). A pickle naming a renamed or deleted class — a
        version-skewed Hub/Display pair, the stale-restart failure mode — raises
        ``AttributeError`` / ``ImportError`` (``ModuleNotFoundError``); a
        structurally broken one raises ``TypeError``. Corrupt base64 makes
        ``b64decode`` raise ``binascii.Error``, which subclasses ``ValueError``
        and so is already caught below — no separate arm is needed. All become
        the same named rejection, and a pickle of a non-element is rejected here
        rather than surfacing as an ``AttributeError`` later in
        ``_wrap_abc_elements``.
        """
        if not isinstance(pickled, str):
            raise ValueError(f"scene element _pickled must be a str, got {pickled!r}")
        try:
            # ``b64decode`` raises ``binascii.Error`` (a ``ValueError`` subclass)
            # on corrupt base64; ``pickle.loads`` raises the rest.
            obj = pickle.loads(base64.b64decode(pickled))
        except (
            ValueError,
            EOFError,
            TypeError,
            AttributeError,
            ImportError,
            pickle.UnpicklingError,
        ) as exc:
            raise ValueError(f"scene element _pickled is not decodable: {exc}") from exc
        if not isinstance(obj, AbcElement):
            raise ValueError(
                f"scene element _pickled is not an Element: {type(obj).__name__}"
            )
        return cast("Element", obj)
