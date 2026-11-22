"""Resolve pre-migration model names in frames from an older Hub."""

from __future__ import annotations

import base64
import pickle
from io import BytesIO
from typing import TYPE_CHECKING, Any, ClassVar, Self, cast

from punt_lux.wire.model.element_abc import Element as AbcElement

if TYPE_CHECKING:
    from punt_lux.wire.model.elements import Element

__all__ = ["ModelUnpickler"]


class ModelUnpickler(pickle.Unpickler):
    """Load shared models without redirecting the retained Hub or PTY packages."""

    _legacy_packages: ClassVar[tuple[tuple[str, str], ...]] = (
        ("punt_lux.domain.", "punt_lux.domain.hub"),
        ("punt_lux.protocol.", "punt_lux.protocol.pty"),
    )

    @classmethod
    def from_base64(cls, payload: str) -> Self:
        """Read the encoded pickle carried by one scene element."""
        return cls(BytesIO(base64.b64decode(payload)))

    @staticmethod
    def require_element(obj: object) -> Element:
        """Refuse non-elements before the Display attempts to wrap handlers."""
        if not isinstance(obj, AbcElement):
            raise ValueError(
                f"scene element _pickled is not an Element: {type(obj).__name__}"
            )
        return cast("Element", obj)

    def find_class(self, module: str, name: str) -> Any:
        """Resolve moved globals at their new module and leave other names intact."""
        for prefix, retained in self._legacy_packages:
            if module.startswith(prefix) and not (
                module == retained or module.startswith(retained + ".")
            ):
                module = "punt_lux.wire.model." + module.removeprefix(prefix)
                break
        return super().find_class(module, name)
