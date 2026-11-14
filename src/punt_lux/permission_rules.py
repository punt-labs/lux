"""The allow rules ``lux enable`` grants in a repo's ``.claude/settings.json``.

Pure data, kept apart from the settings-file mechanics in
:mod:`punt_lux.claude_permissions`.
"""

from __future__ import annotations

from typing import Final

__all__ = ["LUX_RULES"]

# Least privilege (permissions.md §§ 3, 6): the CLI data plane by name -- the
# hub-client groups that mirror the granted MCP tools, plus the read-only
# checks -- so install/uninstall/enable/disable/hook and the hub and display
# service controls keep prompting; skills by scoped name
# (scripts/check-skill-permissions.sh checks _COMMANDS against plugin/commands).
_CLI_SUBCOMMANDS: Final = (
    "beads",
    "callback",
    "display info",
    "display screenshot",
    "display status",
    "doctor",
    "error",
    "event",
    "frame",
    "hub status",
    "menu",
    "ping",
    "scene",
    "session",
    "status",
    "version",
)
_COMMANDS: Final = (
    "callback.pending",
    "display.info",
    "display.screenshot",
    "error.ls",
    "event.ls",
    "frame.raise",
    "frame.remove",
    "lux",
    "menu.ls",
    "menu.set",
    "ping",
    "scene.clear",
    "scene.clear-all",
    "scene.inspect",
    "scene.ls",
    "scene.show",
    "scene.table",
    "scene.update",
    "session.ls",
    "topic.publish",
    "topic.subscribe",
    "topic.unsubscribe",
)

LUX_RULES: Final = (
    "mcp__plugin_lux_lux__*",
    *(f"Bash(lux {name}:*)" for name in _CLI_SUBCOMMANDS),
    *(f"Skill(lux:{name})" for name in _COMMANDS),
)
