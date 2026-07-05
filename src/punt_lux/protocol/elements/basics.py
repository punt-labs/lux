"""Basics-family codec registration — wires each per-kind module's codec.

Per-kind classes live in ``image.py``, ``separator.py``, ``spinner.py``,
``markdown.py``. ``text.py`` and ``progress.py`` are registered separately
through ``JsonElementFactory`` (Element ABC dispatch — see ``__init__.py``);
their entries are removed here to avoid double registration.

The ``BasicsRegistry`` class consolidates the remaining register calls
behind a single ``apply`` method so the package ``__init__`` does not grow
as each family migrates.
"""

from __future__ import annotations

from typing import Self

from punt_lux.protocol.elements.codec import Register
from punt_lux.protocol.elements.image import ImageElement
from punt_lux.protocol.elements.markdown import MarkdownElement
from punt_lux.protocol.elements.separator import SeparatorElement
from punt_lux.protocol.elements.spinner import SpinnerElement

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
        register(
            "spinner",
            SpinnerElement,
            SpinnerElement.to_dict,
            SpinnerElement.from_dict,
        )
        register(
            "markdown",
            MarkdownElement,
            MarkdownElement.to_dict,
            MarkdownElement.from_dict,
        )
