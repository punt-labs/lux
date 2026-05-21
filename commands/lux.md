---
description: "Enable or disable lux"
argument-hint: "y | n"
allowed-tools: ["mcp__plugin_lux_lux__display_mode", "mcp__plugin_lux_lux__set_display_mode", "mcp__plugin_lux_lux__clear", "mcp__plugin_lux-dev_lux__display_mode", "mcp__plugin_lux-dev_lux__set_display_mode", "mcp__plugin_lux-dev_lux__clear", "mcp__lux__display_mode", "mcp__lux__set_display_mode", "mcp__lux__clear"]
---

# /lux command

Enable or disable visual output for this project.

## Usage

- `/lux y` — enable visual output (consumers will render to the lux window)
- `/lux n` — disable visual output, clear the display
- `/lux` — show current display mode

## Implementation

Parse `$ARGUMENTS`. Every call must pass `repo=<your current working
directory>` so the display-mode config is written to the caller's
project, not to `luxd`'s process cwd (which is `$HOME` under launchd —
see lux-r929). Use the absolute path of the project you're operating in.

### `y`

Call `set_display_mode(mode="y", repo="<cwd>")`. Confirm: "Lux display enabled."

### `n`

1. Call `set_display_mode(mode="n", repo="<cwd>")`.
2. Call the `clear` MCP tool to dismiss the window.
3. Confirm: "Lux display disabled."

### No argument or unrecognized

Call `display_mode(repo="<cwd>")` to read the current mode. Report: "Lux display mode: on" or "Lux display mode: off".
