---
description: "Enable or disable lux"
argument-hint: "y | n"
allowed-tools: ["mcp__plugin_lux_lux__display_mode_get", "mcp__plugin_lux_lux__display_mode_set", "mcp__plugin_lux_lux__scene_clear_all", "mcp__plugin_lux-dev_lux__display_mode_get", "mcp__plugin_lux-dev_lux__display_mode_set", "mcp__plugin_lux-dev_lux__scene_clear_all", "mcp__lux__display_mode_get", "mcp__lux__display_mode_set", "mcp__lux__scene_clear_all"]
---

# /lux command

Enable or disable visual output for this project.

## Usage

- `/lux y` — enable visual output (consumers will render to the lux window)
- `/lux n` — disable visual output, clear the display
- `/lux` — show current display mode

## Implementation

Parse `$ARGUMENTS`. Every call must pass `repo="<cwd>"` (replacing
`<cwd>` with the absolute path of your current working directory) so
the display-mode config is written to the caller's project, not to
`luxd`'s process cwd — which is `$HOME` under launchd (see lux-r929).

### `y`

Call `display_mode_set(mode="y", repo="<cwd>")`. Confirm: "Lux display enabled."

### `n`

1. Call `display_mode_set(mode="n", repo="<cwd>")`.
2. Call the `scene_clear_all` MCP tool to dismiss the window.
3. Confirm: "Lux display disabled."

### No argument or unrecognized

Call `display_mode_get(repo="<cwd>")` to read the current mode. Report: "Lux display mode: on" or "Lux display mode: off".
