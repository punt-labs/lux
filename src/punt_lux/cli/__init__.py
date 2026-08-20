"""Noun-grouped Typer sub-apps for the ``lux`` CLI.

Each module in this package defines one Typer sub-app corresponding to one
noun in the design vocabulary (``hub``, ``scene``, ``frame``, ``menu``,
``session``, ``topic``, ``callback``, ``display``, ``event``, ``error``).
The top-level ``punt_lux.__main__`` composes them by name; the top-level
singletons (``ping``, ``doctor``, ``version``, ``enable``, ``disable``,
``install``, ``uninstall``, ``mcp``) live in :mod:`punt_lux.cli.top_level`.
"""

from __future__ import annotations

__all__: list[str] = []
