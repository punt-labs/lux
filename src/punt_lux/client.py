"""Backward-compatibility shim — use ``punt_lux.display_client`` instead."""

from __future__ import annotations

from punt_lux.display_client import DisplayClient as LuxClient

__all__ = ["LuxClient"]
