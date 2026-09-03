---
description: "Enable or disable lux"
argument-hint: "y | n"
allowed-tools: ["Bash", "mcp__plugin_lux_lux__display_mode_get", "mcp__plugin_lux_lux__scene_clear_all", "mcp__plugin_lux-dev_lux__display_mode_get", "mcp__plugin_lux-dev_lux__scene_clear_all", "mcp__lux__display_mode_get", "mcp__lux__scene_clear_all"]
---

# /lux command

Enable or disable visual output for this project.

## Usage

- `/lux y` — enable visual output (consumers will render to the lux window)
- `/lux n` — disable visual output, clear the display
- `/lux` — show current display mode

## Implementation

Parse `$ARGUMENTS`. Enabling and disabling display mode is a user action,
so `/lux y` and `/lux n` run the CLI rather than an MCP tool — a client or
agent may read the display mode but never modify it (DES-088). Every
invocation must pass `--repo <cwd>` (replacing `<cwd>` with the absolute
path of your current working directory) so the display-mode config is
written to the caller's project, not to `luxd`'s process cwd — which is
`$HOME` under launchd (see lux-r929).

### `y`

Run the Bash command `lux display mode on --repo <cwd>`. Confirm: "Lux display enabled."

### `n`

1. Run the Bash command `lux display mode off --repo <cwd>`.
2. Call the `scene_clear_all` MCP tool to dismiss the window.
3. Confirm: "Lux display disabled."

### No argument or unrecognized

Call the `display_mode_get` MCP tool with `repo="<cwd>"` to read the current mode. Report: "Lux display mode: on" or "Lux display mode: off".
