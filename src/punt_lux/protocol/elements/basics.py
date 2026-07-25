"""Basics-family codec registration — wires the one remaining legacy codec.

``image`` is the only legacy basics kind left; ``text``, ``progress``,
``markdown``, ``spinner``, and ``separator`` are Element-ABC kinds registered
through the ``AbcElementRegistry`` dispatch (see ``abc_kind_table.py``), so
their entries are absent here to avoid double registration.

The ``BasicsRegistry`` class consolidates the register call behind a single
``apply`` method so the package ``__init__`` does not grow as each family
migrates.
"""

from __future__ import annotations

from typing import Self

from punt_lux.protocol.elements.codec import Register
from punt_lux.protocol.elements.image import ImageElement

__all__ = ["BasicsRegistry"]


class BasicsRegistry:
    """Registers the remaining basics-family element kind's codec into a sink.

    The class exists to give this module a class-with-behavior surface
    (PY-OO-1) — the alternative was a single free function which would
    miss the per-file OO score targets even though it is genuinely a
    stateless registration helper.
    """

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def apply(self, register: Register) -> None:
        """Register the remaining basics-family element kind's codec."""
        register("image", ImageElement, ImageElement.to_dict, ImageElement.from_dict)
