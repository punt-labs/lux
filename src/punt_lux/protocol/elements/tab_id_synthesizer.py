"""TabIdSynthesizer — assign each wire tab a stable, non-positional id.

A tab's ``tab_id`` is the identity the active-tab selection names, so it must be
stable under reorder and relabel. The agent-supplied wire ``id`` is preferred
and used verbatim (a duplicate is caught by ``TabBarElement.validate``). When a
tab omits its ``id`` the synthesizer derives one from the label — a content key,
not the tab's position — and appends a numeric suffix only when a label repeats,
so the ids stay unique across one tab list.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Self

__all__ = ["TabIdSynthesizer"]


class TabIdSynthesizer:
    """Hand out one stable id per tab, remembering those already assigned.

    Stateful across a single tab list: the ids already handed out drive the
    dedup suffix for a synthesized slug. Construct one per ``decode`` call so the
    dedup scope is exactly one tab bar.
    """

    _seen: set[str]

    def __new__(cls) -> Self:
        self = super().__new__(cls)
        self._seen = set()
        return self

    def id_for(self, tab: Mapping[str, object], label: str) -> str:
        """Return the tab's stable id, recording it so later slugs stay unique."""
        raw_id = tab.get("id")
        if isinstance(raw_id, str) and raw_id:
            tab_id = raw_id
        else:
            tab_id = self._synthesize(label)
        self._seen.add(tab_id)
        return tab_id

    def _synthesize(self, label: str) -> str:
        """Return a content slug of ``label``, suffixed when the slug repeats."""
        base = self._slugify(label)
        if base not in self._seen:
            return base
        suffix = 2
        while f"{base}-{suffix}" in self._seen:
            suffix += 1
        return f"{base}-{suffix}"

    @staticmethod
    def _slugify(label: str) -> str:
        """Return a lowercase hyphen slug of ``label``; ``"tab"`` when empty."""
        slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
        return slug or "tab"
