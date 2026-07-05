"""Encode/decode recursion registry for the layout container codecs.

Container codecs (group, window, tab-bar, …) recurse into their child
elements through a single shared dispatcher rather than importing the
package-level ``element_to_dict`` / ``JsonElementFactory.element_from_dict``
directly.  Importing those eagerly would create a circular import — the
:mod:`protocol.elements` aggregator imports the container module to build
the union and dispatch tables, so the container module cannot import the
dispatchers at module-import time.

The aggregator calls :meth:`ContainerDispatch.install_to_dict` once at
import time with the encode-side function; each tier calls
:meth:`ContainerDispatch.install_from_dict` at startup with its
:meth:`JsonElementFactory.element_from_dict` bound method.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Self

__all__ = ["ContainerDispatch", "RecurseFromDict", "RecurseToDict", "dispatch"]

RecurseToDict = Callable[[Any], dict[str, Any]]
RecurseFromDict = Callable[[dict[str, Any]], Any]


class ContainerDispatch:
    """Holds the package-level encode/decode container recursion targets.

    A single shared instance lives at module scope. Encapsulating the
    two pointers in a class (instead of bare module-level globals)
    avoids the ``global`` statement and the corresponding
    ``PLW0603`` suppressions while preserving the install-once semantics
    container codecs need.
    """

    _to_dict: RecurseToDict | None
    _from_dict: RecurseFromDict | None

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._to_dict = None
        self._from_dict = None
        return self

    def install_to_dict(self, to_dict: RecurseToDict) -> None:
        """Bind the encode-side container recursion function."""
        self._to_dict = to_dict

    def install_from_dict(self, from_dict: RecurseFromDict) -> None:
        """Bind the decode-side container recursion function."""
        self._from_dict = from_dict

    @property
    def to_dict(self) -> RecurseToDict:
        """Return the encode-side recursion function, or raise."""
        if self._to_dict is None:
            msg = "layout codecs used before encode dispatcher installed"
            raise RuntimeError(msg)
        return self._to_dict

    @property
    def from_dict(self) -> RecurseFromDict:
        """Return the decode-side recursion function, or raise."""
        if self._from_dict is None:
            msg = (
                "layout codecs used before decode dispatcher installed — "
                "construct a JsonElementFactory at tier startup and call "
                "container_dispatch.dispatch.install_from_dict("
                "factory.element_from_dict)"
            )
            raise RuntimeError(msg)
        return self._from_dict


dispatch = ContainerDispatch()
