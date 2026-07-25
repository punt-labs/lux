"""Basics-family codec registration — wires each per-kind module's codec.

The remaining legacy basics classes live in ``image.py`` and
``separator.py``. ``text``, ``progress``, ``markdown``, and ``spinner`` are
Element-ABC kinds registered through the ``AbcElementRegistry`` dispatch (see
``abc_kind_table.py``); their entries are absent here to avoid double
registration.

The ``BasicsRegistry`` class consolidates the remaining register calls
behind a single ``apply`` method so the package ``__init__`` does not grow
as each family migrates.
"""

from __future__ import annotations

from typing import Self

from punt_lux.protocol.elements.codec import Register
from punt_lux.protocol.elements.image import ImageElement
from punt_lux.protocol.elements.separator import SeparatorElement

__all__ = ["BasicsRegistry"]


class BasicsRegistry:
    """Registers every basics-family element kind's codec into a Register sink.

    The class exists to give this module a class-with-behavior surface
    (PY-OO-1) — the alternative was a single free function which would
    miss the per-file OO score targets even though it is genuinely a
    stateless registration helper.
    """

    def __new__(cls) -> Self:
        return super().__new__(cls)

    def apply(self, register: Register) -> None:
        """Register every basics-family element kind's codec."""
        register("image", ImageElement, ImageElement.to_dict, ImageElement.from_dict)
        register(
            "separator",
            SeparatorElement,
            SeparatorElement.to_dict,
            SeparatorElement.from_dict,
        )
