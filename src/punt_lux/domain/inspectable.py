"""Inspectable — the single-method introspection interface (PY-DP-11)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable

__all__ = ["Inspectable"]


@runtime_checkable
class Inspectable(Protocol):
    """An element that reports its fully-resolved state for introspection.

    The JSON wire dict omits defaulted fields (the encoder strips them), so
    it cannot answer "does ``label`` read back as ``""``?". ``resolved_props``
    returns every state field including defaults, so a migration test can
    assert an element's value reads back without inspecting pixels.

    Single-method interface (PY-DP-11): each kind adopts ``resolved_props``
    as it migrates, without widening the Element ABC and without forcing the
    not-yet-migrated kinds to implement it. The introspection handler resolves
    it by ``isinstance(elem, Inspectable)`` (PY-TS-10 — never ``hasattr``);
    legacy kinds fall back to their wire dict.
    """

    def resolved_props(self) -> Mapping[str, object]: ...
