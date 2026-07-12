"""Tab — one addressable tab in a ``TabBarElement``.

Lives in its own module so both ``TabBarElement`` (the container) and
``JsonTabBarDecoder`` (which constructs tabs) import it without a runtime import
cycle between the element and its codec.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from punt_lux.domain.element_abc import Element

__all__ = ["Tab"]


@dataclass(frozen=True, slots=True)
class Tab:
    """A stable id, a label, and the children shown when the tab is active.

    The ``tab_id`` is the stable identity the active-tab selection names — stable
    under reorder and relabel, which is what makes the Hub's reconciliation a
    membership check rather than an index clamp (DES-045).
    """

    tab_id: str
    label: str
    children: tuple[Element, ...]
