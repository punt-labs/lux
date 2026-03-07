"""Lux — the paintbrush for Claude. Visual output surface for AI agents."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("punt-lux")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "0.0.0"

__all__: list[str] = []
