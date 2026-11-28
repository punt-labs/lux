"""The permission rules ``lux enable`` grants in a checkout's scoped settings.

Pure data, kept apart from the settings-file mechanics in
:mod:`punt_lux.service.claude_permissions`.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

__all__ = ["LUX_RULES"]

# Broad allow per surface with exact ask carve-outs (permissions.md § 6): ask
# beats allow, so install/uninstall/enable/disable/hook and the hub and display
# service controls still prompt while safe commands, MCP tools and skills work without a
# rule update. A global option before the verb runs under the broad allow: the
# ask tier is a safety net, not a security boundary (punt-kit DES-039).
_SERVICE_VERBS: Final = ("install", "uninstall", "start", "stop", "restart", "doctor")

LUX_RULES: Final[MappingProxyType[str, tuple[str, ...]]] = MappingProxyType(
    {
        "allow": ("Bash(lux:*)", "mcp__plugin_lux_lux__*", "Skill(lux:*)"),
        "ask": (
            *(
                f"Bash(lux {verb}:*)"
                for verb in ("install", "uninstall", "enable", "disable", "hook")
            ),
            *(f"Bash(lux hub {verb}:*)" for verb in _SERVICE_VERBS),
            *(f"Bash(lux display {verb}:*)" for verb in (*_SERVICE_VERBS, "serve")),
        ),
    }
)
