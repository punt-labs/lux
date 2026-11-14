"""The permission rules ``lux enable`` grants in a repo's ``.claude/settings.json``.

Pure data, kept apart from the settings-file mechanics in
:mod:`punt_lux.claude_permissions`.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

__all__ = ["LUX_RULES"]

# Broad allow per surface with exact ask carve-outs (permissions.md § 6): ask
# beats allow, so install/uninstall/enable/disable/hook, the hub and display
# service controls, and ``display mode`` (which grants or revokes these rules)
# keep prompting while new safe commands, MCP tools and skills work without a
# rule update. ``Bash(lux -*)`` asks for a global option before the verb, which
# the verb rules would not match.
_SERVICE_VERBS: Final = ("install", "uninstall", "start", "stop", "restart", "doctor")

LUX_RULES: Final[MappingProxyType[str, tuple[str, ...]]] = MappingProxyType(
    {
        "allow": ("Bash(lux:*)", "mcp__plugin_lux_lux__*", "Skill(lux:*)"),
        "ask": (
            "Bash(lux -*)",
            *(
                f"Bash(lux {verb}:*)"
                for verb in ("install", "uninstall", "enable", "disable", "hook")
            ),
            *(f"Bash(lux hub {verb}:*)" for verb in _SERVICE_VERBS),
            *(
                f"Bash(lux display {verb}:*)"
                for verb in (*_SERVICE_VERBS, "serve", "mode")
            ),
        ),
    }
)
