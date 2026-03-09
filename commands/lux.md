---
description: "Enable or disable lux"
argument-hint: "y | n"
allowed-tools: ["mcp__plugin_lux_lux__display_mode", "mcp__plugin_lux_lux__clear", "mcp__plugin_lux-dev_lux__display_mode", "mcp__plugin_lux-dev_lux__clear", "mcp__lux__display_mode", "mcp__lux__clear"]
---

# /lux command

Enable or disable visual output for this project.

## Usage

- `/lux y` — enable visual output (consumers will render to the lux window)
- `/lux n` — disable visual output, clear the display
- `/lux` — show current display mode

## Implementation

Parse `$ARGUMENTS`:

### `y`

Call the `display_mode` MCP tool with `mode="y"`. Confirm: "Lux display enabled."

### `n`

1. Call the `display_mode` MCP tool with `mode="n"`.
2. Call the `clear` MCP tool to dismiss the window.
3. Confirm: "Lux display disabled."

### No argument or unrecognized

Call the `display_mode` MCP tool with no arguments to read the current mode. Report: "Lux display mode: on" or "Lux display mode: off".
